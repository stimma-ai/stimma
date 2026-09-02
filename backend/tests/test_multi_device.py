"""Multi-device: identity, token verification, and session handling.

Concentrated on the parts that are load-bearing for security — the pinned
certificate, local Firebase token verification, and the session gate — since
those are what stand between a LAN and someone else's library.
"""
import base64
import hashlib
import json
import time

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import serialization

from multi_device import auth, identity, server


# --- identity ---------------------------------------------------------------


def test_generated_cert_fingerprint_matches_der():
    """The published fingerprint must be of the DER the client will see."""
    cert_pem, _key = identity.generate_self_signed_cert("testhost", ["10.0.0.5"])
    published = identity.cert_fingerprint(cert_pem)

    der = x509.load_pem_x509_certificate(cert_pem.encode()).public_bytes(
        serialization.Encoding.DER
    )
    assert published == hashlib.sha256(der).hexdigest()
    assert len(published) == 64


def test_cert_includes_every_route_address_in_san():
    """Whichever route the client picks must pass TLS hostname checks."""
    addresses = ["192.168.1.5", "100.64.0.9"]
    cert_pem, _key = identity.generate_self_signed_cert("testhost", addresses)

    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    present = {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}

    for address in addresses:
        assert address in present
    assert "127.0.0.1" in present


def test_two_devices_get_distinct_ids():
    assert identity.generate_device_id() != identity.generate_device_id()


@pytest.mark.parametrize(
    "address,expected",
    [
        ("100.64.0.1", True),      # start of the CGNAT range Tailscale uses
        ("100.127.255.254", True),
        ("100.68.139.69", True),
        ("192.168.1.5", False),
        ("10.0.0.1", False),
        ("100.63.255.255", False),  # just below the range
        ("100.128.0.0", False),     # just above it
        ("not-an-ip", False),
    ],
)
def test_tailscale_detection(address, expected):
    """Route ordering depends on this: LAN is preferred over the tailnet."""
    assert identity.is_tailscale_address(address) is expected


def test_ensure_identity_is_stable_when_already_persisted():
    class Persisted:
        device_id = "already-set-device-id"
        device_name = "ALPHA"
        cert_pem, key_pem = identity.generate_self_signed_cert("ALPHA", [])

    device_id, name, cert_pem, key_pem = identity.ensure_identity(Persisted)
    assert device_id == "already-set-device-id"
    assert name == "ALPHA"
    assert cert_pem == Persisted.cert_pem
    assert key_pem == Persisted.key_pem


def test_ensure_identity_mints_what_is_missing():
    class Empty:
        device_id = None
        device_name = None
        cert_pem = None
        key_pem = None

    device_id, name, cert_pem, key_pem = identity.ensure_identity(Empty)
    assert device_id and len(device_id) >= 8
    assert name
    assert "BEGIN CERTIFICATE" in cert_pem
    assert "BEGIN PRIVATE KEY" in key_pem


# --- token verification -----------------------------------------------------


def _unsigned_token(claims: dict, kid: str = "test-kid") -> str:
    def seg(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    header = seg({"alg": "RS256", "kid": kid, "typ": "JWT"})
    return f"{header}.{seg(claims)}.{seg({'sig': 'x'})}"


def _valid_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "sub": "firebase-uid-123",
        "aud": auth.FIREBASE_PROJECT_ID,
        "iss": f"https://securetoken.google.com/{auth.FIREBASE_PROJECT_ID}",
        "iat": now - 10,
        "exp": now + 3600,
    }
    claims.update(overrides)
    return claims


@pytest.mark.asyncio
async def test_malformed_tokens_are_rejected_before_any_network_call():
    for bad in ["", "not-a-jwt", "only.two", "a.b.c.d"]:
        with pytest.raises(auth.AuthError):
            await auth.verify_firebase_token(bad)


@pytest.mark.asyncio
async def test_non_rs256_is_rejected():
    """'alg: none' is the classic JWT bypass; refuse anything but RS256."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(_valid_claims()).encode()).rstrip(b"=").decode()
    with pytest.raises(auth.AuthError, match="algorithm"):
        await auth.verify_firebase_token(f"{header}.{body}.")


@pytest.mark.asyncio
async def test_token_without_kid_is_rejected():
    header = base64.urlsafe_b64encode(json.dumps({"alg": "RS256"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(_valid_claims()).encode()).rstrip(b"=").decode()
    with pytest.raises(auth.AuthError, match="key id"):
        await auth.verify_firebase_token(f"{header}.{body}.")


@pytest.mark.asyncio
async def test_unknown_signing_key_is_rejected(monkeypatch):
    async def no_keys(force: bool = False):
        return {}

    monkeypatch.setattr(auth, "_fetch_jwks", no_keys)
    with pytest.raises(auth.AuthError, match="unknown signing key"):
        await auth.verify_firebase_token(_unsigned_token(_valid_claims()))


@pytest.mark.asyncio
async def test_jwks_failure_with_no_cache_is_an_error(monkeypatch):
    """No cached keys and no network: refuse rather than accept blindly."""
    monkeypatch.setattr(auth, "_jwks_cache", {})
    monkeypatch.setattr(auth, "_jwks_fetched_at", 0.0)

    async def boom(*args, **kwargs):
        raise RuntimeError("offline")

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        get = boom

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: FailingClient())
    with pytest.raises(auth.AuthError):
        await auth._fetch_jwks(force=True)


@pytest.mark.asyncio
async def test_stale_jwks_is_preferred_over_failing_closed(monkeypatch):
    """A Google blip must not break an already-trusted LAN link."""
    monkeypatch.setattr(auth, "_jwks_cache", {"kid-1": "cert"})
    monkeypatch.setattr(auth, "_jwks_fetched_at", 0.0)  # forces a refresh attempt

    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise RuntimeError("offline")

    monkeypatch.setattr(auth.httpx, "AsyncClient", lambda **kwargs: FailingClient())
    assert await auth._fetch_jwks() == {"kid-1": "cert"}


# --- sessions ---------------------------------------------------------------


@pytest.fixture
def isolated_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_sessions_path", lambda: tmp_path / "sessions.json")
    monkeypatch.setattr(auth, "own_account_uid", lambda: "acct-1")
    yield tmp_path


def test_session_round_trips(isolated_sessions):
    token = auth.issue_session("client-device", "acct-1")
    record = auth.verify_session(token)
    assert record is not None
    assert record["client_device_id"] == "client-device"


def test_unknown_and_empty_sessions_are_refused(isolated_sessions):
    auth.issue_session("client-device", "acct-1")
    assert auth.verify_session("not-a-real-session") is None
    assert auth.verify_session("") is None
    assert auth.verify_session(None) is None


def test_sessions_are_stored_hashed_not_in_the_clear(isolated_sessions):
    """A readable sessions file must not be a set of usable credentials."""
    token = auth.issue_session("client-device", "acct-1")
    raw = (isolated_sessions / "sessions.json").read_text()
    assert token not in raw
    assert hashlib.sha256(token.encode()).hexdigest() in raw


def test_revoking_drops_every_session(isolated_sessions):
    """Turning serving off is one of the two real ways to cut a device off."""
    a = auth.issue_session("device-a", "acct-1")
    b = auth.issue_session("device-b", "acct-1")
    auth.revoke_all_sessions()
    assert auth.verify_session(a) is None
    assert auth.verify_session(b) is None


def test_session_is_refused_after_the_account_changes(tmp_path, monkeypatch):
    """Signing into a different account must not inherit the old trust."""
    monkeypatch.setattr(auth, "_sessions_path", lambda: tmp_path / "sessions.json")
    monkeypatch.setattr(auth, "own_account_uid", lambda: "acct-1")
    token = auth.issue_session("client-device", "acct-1")
    assert auth.verify_session(token) is not None

    monkeypatch.setattr(auth, "own_account_uid", lambda: "acct-2")
    assert auth.verify_session(token) is None


# --- port allocation ---------------------------------------------------------
#
# Port assignment must never be something a developer or user debugs. Several
# installs share a machine routinely (channels, sandboxes, dev beside release)
# and unrelated software may hold any number we would have picked.


def test_zero_means_the_os_picks():
    sock = server._bind_listener(0)
    try:
        assert sock.getsockname()[1] > 0
    finally:
        sock.close()


def test_a_free_preferred_port_is_honoured():
    probe = server._bind_listener(0)
    free = probe.getsockname()[1]
    probe.close()

    sock = server._bind_listener(free)
    try:
        assert sock.getsockname()[1] == free
    finally:
        sock.close()


def test_a_taken_preferred_port_falls_back_instead_of_raising():
    """The second install on a machine must just work."""
    first = server._bind_listener(0)
    taken = first.getsockname()[1]
    try:
        second = server._bind_listener(taken)
        try:
            assert second.getsockname()[1] != taken
            assert second.getsockname()[1] > 0
        finally:
            second.close()
    finally:
        first.close()


def test_many_installs_on_one_machine_all_get_distinct_ports():
    socks = [server._bind_listener(8420) for _ in range(5)]
    try:
        ports = {s.getsockname()[1] for s in socks}
        assert len(ports) == 5
    finally:
        for s in socks:
            s.close()


# --- roster membership --------------------------------------------------------
#
# Being signed in on a machine is not consent to have that machine listed on
# every other machine you own. The roster is what the user OFFERED, so "not
# serving" and "not listed" have to be the same state rather than two that can
# drift apart.


@pytest.fixture
def fake_registry(monkeypatch):
    """Capture what would be published, without touching config or the cloud."""
    from multi_device import service

    published: list[dict] = []

    async def capture(**kwargs):
        published.append(kwargs)
        return []

    monkeypatch.setattr(service.registry, "register", capture)
    monkeypatch.setattr(
        service,
        "ensure_persisted_identity",
        lambda: ("device-alpha", "ALPHA", _CERT_PEM, _KEY_PEM),
    )
    monkeypatch.setattr(service, "get_settings", lambda: _FakeSettings())
    return published


_CERT_PEM, _KEY_PEM = identity.generate_self_signed_cert("ALPHA", ["192.168.1.5"])


class _FakeMultiDevice:
    port = 0
    last_port = 43239
    serving = False


class _FakeSettings:
    multi_device = _FakeMultiDevice()


@pytest.mark.asyncio
async def test_a_serving_install_publishes_how_to_reach_it(monkeypatch, fake_registry):
    from multi_device import service

    monkeypatch.setattr(service.server, "is_serving", lambda: True)
    monkeypatch.setattr(service.server, "serving_port", lambda: 43239)
    monkeypatch.setattr(
        service.registry, "build_routes", lambda port: [{"kind": "lan", "host": "h", "port": port}]
    )

    await service.register_now()

    assert len(fake_registry) == 1
    payload = fake_registry[0]
    assert payload["serving"] is True
    assert payload["routes"] == [{"kind": "lan", "host": "h", "port": 43239}]
    assert payload["cert_fingerprint"] == identity.cert_fingerprint(_CERT_PEM)


@pytest.mark.asyncio
async def test_a_non_serving_install_publishes_nothing_to_connect_to(monkeypatch, fake_registry):
    """The registry reads this as an unregister; the row leaves the roster."""
    from multi_device import service

    monkeypatch.setattr(service.server, "is_serving", lambda: False)
    monkeypatch.setattr(service.server, "serving_port", lambda: None)

    await service.register_now()

    payload = fake_registry[0]
    assert payload["serving"] is False
    assert payload["routes"] == []
    # No fingerprint means there is nothing another machine could pin, which is
    # the point: an un-offered install is not connectable, not merely hidden.
    assert payload["cert_fingerprint"] is None


# --- presence -----------------------------------------------------------------


def test_the_account_socket_carries_this_installs_identity():
    """Presence is this socket. Without the id it cannot be attributed."""
    from cloud_events import DEVICE_ID_HEADER, events_headers

    headers = events_headers("id-token", "device-alpha")
    assert headers[DEVICE_ID_HEADER] == "device-alpha"
    assert headers["Authorization"] == "Bearer id-token"


def test_the_account_socket_still_connects_without_an_identity():
    """A device id we could not read must not cost us account events."""
    from cloud_events import DEVICE_ID_HEADER, events_headers

    headers = events_headers("id-token", None)
    assert DEVICE_ID_HEADER not in headers
    assert headers["Authorization"] == "Bearer id-token"


def test_the_identity_never_goes_in_the_query_string():
    """A Cloudflare route pattern with no trailing wildcard does not match a
    URL carrying a query string: `?deviceId=` fell through the API worker
    entirely and hit the marketing site's 404. Keep the URL bare."""
    from cloud_events import events_url

    assert events_url("https://api.example.com/") == "wss://api.example.com/account-events-v1"
    assert "?" not in events_url("http://localhost:8787")
