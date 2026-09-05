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

from multi_device import auth, identity, registry, server


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


def test_route_budget_never_crowds_out_tailscale(monkeypatch):
    addresses = [f"10.0.0.{n}" for n in range(1, 10)] + ["100.64.0.9"]
    monkeypatch.setattr(registry, "local_addresses", lambda: addresses)

    routes = registry.build_routes(43239)

    assert len(routes) == 8
    assert [route["kind"] for route in routes].count("lan") == 7
    assert routes[-1] == {"kind": "tailscale", "host": "100.64.0.9", "port": 43239}


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


def test_account_identity_is_cached_for_request_hot_path(monkeypatch):
    """A thumbnail burst must not launch the credential store per request."""
    from auth_storage import load_auth_state as real_load_auth_state

    calls = 0

    def fake_load_auth_state():
        nonlocal calls
        calls += 1
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "acct-1"}).encode()).decode().rstrip("=")
        return {"id_token": f"header.{payload}.signature"}

    monkeypatch.setattr("auth_storage.load_auth_state", fake_load_auth_state)
    monkeypatch.setattr(auth, "_own_account_uid_cache", auth._ACCOUNT_UID_UNSET)
    try:
        assert auth.own_account_uid() == "acct-1"
        assert auth.own_account_uid() == "acct-1"
        assert calls == 1
    finally:
        monkeypatch.setattr("auth_storage.load_auth_state", real_load_auth_state)


def _auth_state_with_uid(uid):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": uid}).encode()).decode().rstrip("=")
    return {"id_token": f"header.{payload}.signature"}


def test_a_missing_token_is_not_cached_as_signed_out(monkeypatch):
    """After a restart the ID token exists only once the first refresh has run,
    and the serving socket is listening before that. A bootstrap in that window
    must not brand the install signed-out for the life of the process."""
    from auth_storage import load_auth_state as real_load_auth_state

    state = {"refresh_token": "r"}
    monkeypatch.setattr("auth_storage.load_auth_state", lambda: dict(state))
    monkeypatch.setattr(auth, "_own_account_uid_cache", auth._ACCOUNT_UID_UNSET)
    try:
        assert auth.own_account_uid() is None
        state.update(_auth_state_with_uid("acct-1"))
        assert auth.own_account_uid() == "acct-1"
    finally:
        monkeypatch.setattr("auth_storage.load_auth_state", real_load_auth_state)


@pytest.mark.asyncio
async def test_bootstrap_identity_refreshes_the_token_before_refusing(monkeypatch):
    """A refresh token on disk with no ID token in memory is a signed-in
    install that has not talked to Firebase yet, not a signed-out one."""
    from auth_storage import load_auth_state as real_load_auth_state
    import firebase_auth

    state = {"refresh_token": "r"}
    refreshes = 0

    async def fake_get_valid_id_token(**_kwargs):
        nonlocal refreshes
        refreshes += 1
        state.update(_auth_state_with_uid("acct-1"))
        return state["id_token"]

    monkeypatch.setattr("auth_storage.load_auth_state", lambda: dict(state))
    monkeypatch.setattr(firebase_auth, "get_valid_id_token", fake_get_valid_id_token)
    monkeypatch.setattr(auth, "_own_account_uid_cache", auth._ACCOUNT_UID_UNSET)
    try:
        assert await auth.ensure_own_account_uid() == "acct-1"
        assert refreshes == 1
        # Found once, it is served from the cache: no second refresh.
        assert await auth.ensure_own_account_uid() == "acct-1"
        assert refreshes == 1
    finally:
        monkeypatch.setattr("auth_storage.load_auth_state", real_load_auth_state)


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


def test_session_is_refused_when_the_server_has_no_account(tmp_path, monkeypatch):
    """Persisted credentials must not turn a signed-out server into an
    account-less bearer-token service after a restart."""
    monkeypatch.setattr(auth, "_sessions_path", lambda: tmp_path / "sessions.json")
    monkeypatch.setattr(auth, "own_account_uid", lambda: "acct-1")
    token = auth.issue_session("client-device", "acct-1")
    assert auth.verify_session(token) is not None

    monkeypatch.setattr(auth, "own_account_uid", lambda: None)
    assert auth.verify_session(token) is None


@pytest.mark.asyncio
async def test_serving_gate_marks_only_its_own_session_rejections(monkeypatch):
    """The proxy needs an unambiguous signal; an application's ordinary 401
    must not make Electron rotate a valid device session."""
    monkeypatch.setattr(server, "verify_session", lambda _token: None)
    sent = []

    async def inner_app(_scope, _receive, _send):
        raise AssertionError("an unauthenticated request reached the app")

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    gate = server.ServingGate(inner_app, lambda: "server-device")
    await gate(
        {"type": "http", "path": "/api/settings", "headers": [], "method": "GET"},
        receive,
        send,
    )

    start = sent[0]
    assert start["status"] == 401
    assert server.SESSION_INVALID_HEADER in start["headers"]


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


# --- diagnosing a missing roster ---------------------------------------------
#
# "No roster" has two causes that look identical from the outside and are not
# remotely the same problem. Reporting an unreachable registry as a signed-out
# account sends everyone to look at the wrong thing, while the client quietly
# keeps showing a cached list.


@pytest.mark.asyncio
async def test_a_registry_that_does_not_answer_is_an_error_not_a_sign_out(monkeypatch):
    from multi_device import registry

    async def headers():
        return {"Authorization": "Bearer t"}

    class Failing:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            raise RuntimeError("404 Not Found")

    monkeypatch.setattr(registry, "_cloud_headers", headers)
    monkeypatch.setattr(registry, "is_privacy_lockdown_enabled", lambda: False)
    monkeypatch.setattr(registry.httpx, "AsyncClient", lambda **kwargs: Failing())

    with pytest.raises(registry.RegistryUnavailable, match="404"):
        await registry.list_devices()


@pytest.mark.asyncio
async def test_being_signed_out_is_not_an_error(monkeypatch):
    from multi_device import registry

    async def no_headers():
        return None

    monkeypatch.setattr(registry, "_cloud_headers", no_headers)
    monkeypatch.setattr(registry, "is_privacy_lockdown_enabled", lambda: False)

    assert await registry.list_devices() is None


# --- sign-out -----------------------------------------------------------------
#
# "Signed out = the feature doesn't exist." A server that keeps answering to
# satellites after its account signed out is the opposite of that, so logout
# must stop serving, drop every issued session, and leave the roster — while
# the account token is still good enough to reach the registry.


@pytest.fixture
def signed_in_server(monkeypatch, fake_registry, isolated_sessions):
    """A serving install with the side effects of apply_serving captured."""
    from multi_device import service

    calls: dict[str, list] = {"stop_serving": [], "stop_heartbeat": [], "patched": []}
    serving = {"on": True}

    async def stop_serving():
        calls["stop_serving"].append(True)
        serving["on"] = False

    monkeypatch.setattr(service, "_app", object())
    monkeypatch.setattr(service.server, "is_serving", lambda: serving["on"])
    monkeypatch.setattr(service.server, "serving_port", lambda: 43239 if serving["on"] else None)
    monkeypatch.setattr(service.server, "stop_serving", stop_serving)
    monkeypatch.setattr(
        service.registry, "stop_heartbeat", lambda: calls["stop_heartbeat"].append(True)
    )
    monkeypatch.setattr(
        service, "_patch_multi_device", lambda **changes: calls["patched"].append(changes)
    )

    async def no_broadcast():
        pass

    monkeypatch.setattr(service, "notify_devices_changed", no_broadcast)
    return calls, fake_registry


@pytest.mark.asyncio
async def test_signing_out_stops_serving_and_cuts_every_satellite_off(signed_in_server):
    from multi_device import service

    calls, published = signed_in_server
    a = auth.issue_session("device-a", "acct-1")
    b = auth.issue_session("device-b", "acct-1")

    await service.sign_out()

    assert calls["stop_serving"] == [True]
    assert calls["stop_heartbeat"] == [True]
    # Persisted off, not merely paused: the toggle and the listener agree.
    assert {"serving": False} in calls["patched"]
    # The registry saw an unregister, so the row leaves other installs' pickers.
    assert published[-1]["serving"] is False
    assert published[-1]["cert_fingerprint"] is None
    # verify_session is the gate every proxied request passes through.
    assert auth.verify_session(a) is None
    assert auth.verify_session(b) is None


@pytest.mark.asyncio
async def test_signing_out_while_not_serving_still_drops_sessions(monkeypatch, isolated_sessions):
    """An install that served earlier and then turned serving off may still
    hold no live listener but the sessions file is what grants access."""
    from multi_device import service

    class Off:
        class multi_device:
            serving = False

    monkeypatch.setattr(service, "_app", object())
    monkeypatch.setattr(service.server, "is_serving", lambda: False)
    monkeypatch.setattr(service, "get_settings", lambda: Off())
    stopped = []
    monkeypatch.setattr(service.registry, "stop_heartbeat", lambda: stopped.append(True))

    async def must_not_run(enabled):
        raise AssertionError("apply_serving should not run when nothing is serving")

    monkeypatch.setattr(service, "apply_serving", must_not_run)
    token = auth.issue_session("device-a", "acct-1")

    await service.sign_out()

    assert auth.verify_session(token) is None
    assert stopped == [True]


@pytest.mark.asyncio
async def test_a_failure_to_stop_serving_does_not_block_sign_out(monkeypatch, isolated_sessions):
    from multi_device import service

    class On:
        class multi_device:
            serving = True

    monkeypatch.setattr(service, "_app", object())
    monkeypatch.setattr(service.server, "is_serving", lambda: True)
    monkeypatch.setattr(service, "get_settings", lambda: On())
    monkeypatch.setattr(service.registry, "stop_heartbeat", lambda: None)

    async def boom(enabled):
        raise RuntimeError("listener wedged")

    monkeypatch.setattr(service, "apply_serving", boom)
    token = auth.issue_session("device-a", "acct-1")

    await service.sign_out()  # must not raise

    # Even when the listener could not be torn down, the sessions are gone.
    assert auth.verify_session(token) is None


def test_docker_bridges_do_not_crowd_out_host_interfaces(monkeypatch):
    from types import SimpleNamespace
    import socket
    def addr(value):
        return [SimpleNamespace(family=socket.AF_INET, address=value)]
    interfaces = {f'br-{n}': addr(f'172.20.{n}.1') for n in range(10)}
    interfaces.update({'eth0': addr('192.168.50.2'), 'eth1': addr('10.20.30.2'),
                       'tailscale0': addr('100.64.0.9'), 'lo': addr('127.0.0.1')})
    monkeypatch.delenv('STIMMA_ADVERTISE_HOST', raising=False)
    monkeypatch.setattr(identity.psutil, 'net_if_addrs', lambda: interfaces)
    monkeypatch.setattr(identity.psutil, 'net_if_stats', lambda: {})
    monkeypatch.setattr(identity.socket, 'getaddrinfo', lambda *args: [])
    routes = registry.build_routes(9193)
    assert routes[:2] == [{'kind': 'lan', 'host': host, 'port': 9193}
                          for host in ('192.168.50.2', '10.20.30.2')]
    assert routes[-1] == {'kind': 'tailscale', 'host': '100.64.0.9', 'port': 9193}
    interfaces['eth0'] = addr('192.168.50.3')
    refreshed = registry.build_routes(9193)
    assert refreshed[0]['host'] == '192.168.50.3'
    assert all(route['host'] != '192.168.50.2' for route in refreshed)
