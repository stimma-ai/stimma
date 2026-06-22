"""
CI privacy guard tests (PRIVACY posture, behavioral).

Asserts the load-bearing privacy gates:
- dev distribution (the repo default) -> telemetry is a permanent no-op
  (no buffering, no network).
- official distribution -> nothing sent when consent is off; pre-consent
  events buffer locally with zero network, flush on consent-on, and are
  discarded on consent-off (D14).
- The single ``telemetry_enabled {enabled: false}`` toggle-off transition
  event is the documented carve-out (sent last).
- ``DO_NOT_TRACK=1`` kills telemetry regardless of consent and currently
  also suppresses the feature-flags fetch, update check, and region call.
- The User-Agent helper emits exactly version/os/arch/branch/install-id,
  and the telemetry body carries no install id.
"""
import asyncio
import re
import types
import uuid

import pytest


# ── Helpers ─────────────────────────────────────────────────────────────


def _fake_settings(telemetry_enabled=None, install_id=None, hash_salt=None,
                   disable_update_check=False):
    telemetry = types.SimpleNamespace(
        enabled=telemetry_enabled,
        install_id=install_id or str(uuid.uuid4()),
        hash_salt=hash_salt or "a" * 64,
        model_dump=lambda: {
            "enabled": telemetry_enabled,
            "install_id": install_id,
            "hash_salt": hash_salt,
        },
    )
    return types.SimpleNamespace(
        telemetry=telemetry,
        cloud=types.SimpleNamespace(base_url="https://cloud.invalid"),
        compliance=types.SimpleNamespace(country=None, regime=None, checked_at=None),
        disable_update_check=disable_update_check,
    )


@pytest.fixture
def patch_settings(monkeypatch):
    """Patch config.get_settings with a controllable fake."""
    def _apply(**kwargs):
        settings = _fake_settings(**kwargs)
        monkeypatch.setattr("config.get_settings", lambda: settings)
        return settings
    return _apply


@pytest.fixture
def fresh_env(monkeypatch):
    """Reset distribution/DNT env and the user_agent module caches."""
    monkeypatch.delenv("STIMMA_DISTRIBUTION", raising=False)
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    import user_agent
    monkeypatch.setattr(user_agent, "_install_id", None)
    monkeypatch.setattr(user_agent, "_app_version", None)
    monkeypatch.setattr(user_agent, "_app_branch", None)
    return monkeypatch


def _make_client(monkeypatch):
    """A TelemetryClient whose network layer records instead of sending."""
    from telemetry import TelemetryClient
    client = TelemetryClient()
    sent_batches = []

    async def _record(url, body, headers):
        sent_batches.append((url, body, headers))

    monkeypatch.setattr(client, "_post_with_retries", _record)
    monkeypatch.setattr(client, "_get_user_id", lambda: None)
    return client, sent_batches


# ── Distribution gate ───────────────────────────────────────────────────


def test_repo_default_distribution_is_dev(fresh_env):
    """The repo's default build produces 'dev' — only release CI sets official."""
    from distribution import get_distribution, is_official
    assert get_distribution() == "dev"
    assert not is_official()


@pytest.mark.asyncio
async def test_dev_distribution_telemetry_is_permanent_noop(fresh_env, patch_settings, monkeypatch):
    """dev build: no buffering, no network — even with consent 'on'."""
    patch_settings(telemetry_enabled=True)
    client, sent = _make_client(monkeypatch)

    client.track("anything", {"x": 1})
    client.capture_exception(ValueError("boom"))
    assert client._queue == []  # not even buffered

    await client.flush()
    client.on_consent_changed(True)
    await asyncio.sleep(0)
    assert sent == []


# ── Official-build consent gates (D14) ──────────────────────────────────


@pytest.mark.asyncio
async def test_official_consent_off_sends_nothing(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    patch_settings(telemetry_enabled=False)
    client, sent = _make_client(monkeypatch)

    client.track("event_a")
    assert client._queue == []
    await client.flush()
    assert sent == []


@pytest.mark.asyncio
async def test_preconsent_buffers_locally_with_zero_network(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    patch_settings(telemetry_enabled=None)  # undetermined
    client, sent = _make_client(monkeypatch)

    client.track("first_run")
    client.track("screen_viewed", {"screen": "onboarding"}, category="navigation")
    assert len(client._queue) == 2  # buffered locally

    await client.flush()  # zero network while undetermined
    assert sent == []
    assert len(client._queue) == 2


@pytest.mark.asyncio
async def test_preconsent_buffer_flushes_on_consent_on(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    patch_settings(telemetry_enabled=None)
    client, sent = _make_client(monkeypatch)

    client.track("first_run")
    client.track("onboarding_completed")
    client.on_consent_changed(True)
    await asyncio.sleep(0.01)

    assert len(sent) == 1
    _, body, _ = sent[0]
    events = [e["event"] for e in body["events"]]
    assert "first_run" in events
    assert "onboarding_completed" in events
    # The consent-on transition event rides along
    assert "telemetry_enabled" in events


@pytest.mark.asyncio
async def test_preconsent_buffer_discarded_on_consent_off(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    patch_settings(telemetry_enabled=None)
    client, sent = _make_client(monkeypatch)

    client.track("first_run")
    client.on_consent_changed(False)
    await asyncio.sleep(0.01)

    assert client._queue == []
    assert sent == []  # nothing egresses; no carve-out from undetermined


@pytest.mark.asyncio
async def test_toggle_off_carveout_event_is_last_thing_sent(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    patch_settings(telemetry_enabled=True)
    client, sent = _make_client(monkeypatch)

    client.track("tool_used", {"taskType": "text-to-image"})
    client.on_consent_changed(False)
    await asyncio.sleep(0.01)

    assert len(sent) == 1
    _, body, _ = sent[0]
    events = body["events"]
    assert events[-1]["event"] == "telemetry_enabled"
    assert events[-1]["properties"] == {"enabled": False}

    # And after the transition, nothing more goes out.
    client.track("tool_used")
    await client.flush()
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_telemetry_body_shape_has_no_install_id(fresh_env, patch_settings, monkeypatch):
    """Envelope: {sessionId, userId?, events[]} — identity rides the UA only."""
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    patch_settings(telemetry_enabled=True)
    client, sent = _make_client(monkeypatch)

    client.track("event_a", {"k": "v"}, category="feature")
    await client.flush()

    assert len(sent) == 1
    _, body, _ = sent[0]
    assert set(body.keys()) <= {"sessionId", "userId", "events"}
    assert "installId" not in body
    assert body["sessionId"]
    event = body["events"][0]
    assert set(event.keys()) == {"event", "category", "properties", "timestamp"}
    assert event["category"] == "feature"
    assert isinstance(event["timestamp"], int)


# ── DO_NOT_TRACK=1 is absolute for telemetry ────────────────────────────


@pytest.mark.asyncio
async def test_dnt_kills_telemetry_regardless_of_consent(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    fresh_env.setenv("DO_NOT_TRACK", "1")
    patch_settings(telemetry_enabled=True)  # consent ON — DNT still wins
    client, sent = _make_client(monkeypatch)

    client.track("event_a")
    assert client._queue == []  # no buffering under DNT
    await client.flush()
    client.on_consent_changed(True)
    await asyncio.sleep(0)
    assert sent == []


@pytest.mark.asyncio
async def test_dnt_suppresses_flags_fetch(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("DO_NOT_TRACK", "1")
    patch_settings()
    import feature_flags as ff
    monkeypatch.setattr(ff, "_load_cache", lambda: {})

    called = []

    async def _fail_fetch(self):
        called.append(True)

    monkeypatch.setattr(ff.FeatureFlagClient, "_fetch_once", _fail_fetch)
    client = ff.FeatureFlagClient()
    await client.start()
    await asyncio.sleep(0.05)
    assert client._poll_task is None  # no fetch loop at all
    assert called == []
    # Local defaults still work
    assert client.get_bool("nonexistent_flag", False) is False
    await client.stop()


def test_dnt_suppresses_update_check(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    fresh_env.setenv("DO_NOT_TRACK", "1")
    patch_settings()
    import update_check
    monkeypatch.setattr("user_agent.get_app_branch", lambda: "production")
    assert update_check.should_check() is False


@pytest.mark.asyncio
async def test_settings_api_surfaces_dnt_active(client, monkeypatch):
    """GET /api/settings exposes ``dnt_active`` so the frontend can gate
    the Tauri updater's automatic checks on it. DNT is the telemetry
    off-switch and also gates several nonessential automatic fetches.
    The frontend starts its updater loop only when ``dnt_active`` is
    false; manual user-initiated checks remain available."""
    monkeypatch.delenv("DO_NOT_TRACK", raising=False)
    response = await client.get("/api/settings")
    assert response.status_code == 200
    data = response.json()
    assert data["dnt_active"] is False
    assert data["sandbox"] == "default"

    monkeypatch.setenv("DO_NOT_TRACK", "1")
    response = await client.get("/api/settings")
    assert response.status_code == 200
    assert response.json()["dnt_active"] is True


@pytest.mark.asyncio
async def test_dnt_suppresses_region_call(fresh_env, patch_settings, monkeypatch):
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    fresh_env.setenv("DO_NOT_TRACK", "1")
    patch_settings()
    import compliance_region

    class _NoNetwork:
        def __init__(self, *a, **k):
            raise AssertionError("region call attempted under DNT")

    monkeypatch.setattr(compliance_region.httpx, "AsyncClient", _NoNetwork)
    region = await compliance_region.get_region()
    assert region["regime"] == "optin"  # safe default, default-off


@pytest.mark.asyncio
async def test_dev_build_never_calls_region(fresh_env, patch_settings, monkeypatch):
    patch_settings()
    import compliance_region

    class _NoNetwork:
        def __init__(self, *a, **k):
            raise AssertionError("region call attempted in dev build")

    monkeypatch.setattr(compliance_region.httpx, "AsyncClient", _NoNetwork)
    region = await compliance_region.get_region()
    assert region["regime"] == "optin"


# ── Update-check gating ─────────────────────────────────────────────────


def test_update_check_gating(fresh_env, patch_settings, monkeypatch):
    import update_check

    # dev distribution: never
    patch_settings()
    assert update_check.should_check() is False

    # official + update branch: yes
    fresh_env.setenv("STIMMA_DISTRIBUTION", "official")
    monkeypatch.setattr("user_agent.get_app_branch", lambda: "production")
    assert update_check.should_check() is True

    # official but not on an update branch (source-style): no
    monkeypatch.setattr("user_agent.get_app_branch", lambda: "dev")
    assert update_check.should_check() is False

    # disable_update_check config: no
    monkeypatch.setattr("user_agent.get_app_branch", lambda: "beta")
    patch_settings(disable_update_check=True)
    assert update_check.should_check() is False


# ── User-Agent helper (§2.6) ────────────────────────────────────────────


def test_user_agent_emits_exactly_version_os_arch_branch_install_id(fresh_env, patch_settings, monkeypatch):
    install_id = str(uuid.uuid4())
    patch_settings(install_id=install_id)
    import user_agent
    monkeypatch.setattr(user_agent, "get_app_version", lambda: "1.2.3")
    monkeypatch.setattr(user_agent, "get_app_branch", lambda: "dev")

    ua = user_agent.user_agent()
    match = re.fullmatch(
        r"Stimma/(?P<version>\S+) \((?P<os>[^;]+); (?P<arch>[^;]+); (?P<branch>[^)]+)\) "
        r"install/(?P<install>[0-9a-f-]{36})",
        ua,
    )
    assert match, f"UA format mismatch: {ua}"
    assert match.group("version") == "1.2.3"
    assert match.group("os") in ("macos", "windows", "linux")
    assert match.group("arch") in ("arm64", "x64") or match.group("arch")
    assert match.group("branch") == "dev"
    assert match.group("install") == install_id
    # Nothing else rides along
    assert ua.count("install/") == 1


# ── Salted object hashes ────────────────────────────────────────────────


def test_salted_hash_is_stable_and_irreversible(fresh_env, patch_settings, monkeypatch):
    patch_settings(hash_salt="0" * 64)
    import object_hash
    monkeypatch.setattr(object_hash, "_salt", None)

    h1 = object_hash.salted_hash("flow-123")
    h2 = object_hash.salted_hash("flow-123")
    assert h1 == h2
    assert "flow-123" not in h1
    assert re.fullmatch(r"[0-9a-f]{16}", h1)
    assert object_hash.salted_hash("flow-124") != h1


# ── toolRef / toolSource ────────────────────────────────────────────────


def test_user_tool_ids_are_hashed_catalog_ids_pass_verbatim(fresh_env, patch_settings, monkeypatch):
    patch_settings(hash_salt="0" * 64)
    import object_hash
    monkeypatch.setattr(object_hash, "_salt", None)
    from tool_ref import tool_ref_for

    ref, source = tool_ref_for("builtin:upscale", provider_id="builtin")
    assert source == "builtin"
    assert ref == "builtin:upscale"

    ref, source = tool_ref_for("comfyui:my secret workflow", provider_id="comfyui-local")
    assert source == "user"
    assert "secret" not in ref
    assert re.fullmatch(r"[0-9a-f]{16}", ref)

    ref, source = tool_ref_for("flux-pro", provider_id="stimma-cloud")
    assert source == "cloud"
    assert ref == "flux-pro"


# ── STP server-field validator (D15) ────────────────────────────────────


def test_stp_server_identity_validator():
    from stp_identity import parse_server_identity

    assert parse_server_identity("ComfyUI-Stimma/1.1.0") == {
        "productName": "ComfyUI-Stimma",
        "productVersion": "1.1.0",
    }
    # Unknown products: name munged to 'other', version kept when shaped
    ident = parse_server_identity("SomeServer/2.0.1-beta.2")
    assert ident["productName"] == "other"
    assert ident["productVersion"] == "2.0.1-beta.2"
    # Version not version-shaped -> dropped
    ident = parse_server_identity("ComfyUI-Stimma/whatever")
    assert ident == {"productName": "ComfyUI-Stimma"}
    # Missing/garbage -> unknown
    assert parse_server_identity(None) == {"productName": "unknown"}
    assert parse_server_identity("no-slash-here") == {"productName": "unknown"}
    # User-content-shaped strings never pass through
    ident = parse_server_identity("my-LAN-box-name/1.0")
    assert ident["productName"] == "other"


# ── endpointClass classifier ────────────────────────────────────────────


def test_endpoint_class_classifier():
    from endpoint_class import endpoint_class

    assert endpoint_class("https://api.openai.com/v1") == "openai"
    assert endpoint_class("https://api.anthropic.com") == "anthropic"
    assert endpoint_class("https://openrouter.ai/api/v1") == "openrouter"
    assert endpoint_class("https://api.groq.com/openai/v1") == "other_known"
    assert endpoint_class("http://localhost:8000/v1") == "localhost"
    assert endpoint_class("http://127.0.0.1:1234/v1") == "localhost"
    assert endpoint_class("http://192.168.1.50:8000/v1") == "lan"
    assert endpoint_class("http://my-gpu-box:8000/v1") == "lan"
    assert endpoint_class("http://my-box.local:8000/v1") == "lan"
    assert endpoint_class("https://llm.example.com/v1") == "custom"
    assert endpoint_class("") == "custom"
    assert endpoint_class(None) == "custom"


# ── Refusal classifier ──────────────────────────────────────────────────


def test_shared_refusal_classifier():
    from refusal_detection import is_refusal

    assert is_refusal("I cannot help with that request.")
    assert is_refusal("I'm unable to generate that content.")
    assert is_refusal("Sorry, but that violates the guidelines.")
    # Structured output is never a refusal
    assert not is_refusal('["I cannot believe it is a list item"]')
    assert not is_refusal('{"prompt": "a cat"}')
    assert not is_refusal("A serene mountain lake at golden hour.")
    assert not is_refusal("")
    assert not is_refusal(None)
