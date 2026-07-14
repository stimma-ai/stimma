"""
Telemetry instrumentation tests (catalog v2 sweep).

Covers the trickiest emissions:
- generation_pipeline_completed settle semantics (once per pipeline,
  chain-step jobs excluded, retry re-arms the guard, property shapes);
- toolRef/toolSource classification + closed errorType / errorHash;
- refusal classification feeding agent_turn_completed via the shared
  classifier (status failed + errorType refusal, completed otherwise);
- actor attribution on set/grid events;
- salted-hash prefix-convention stability (per-entity hashes are stable
  within an install and distinct across entity types).
"""
import asyncio
import json
import types
import uuid
from datetime import datetime, timedelta

import pytest


class _CapturingClient:
    def __init__(self):
        self.events = []

    def track(self, event, properties=None, category="app"):
        self.events.append({
            "event": event,
            "properties": dict(properties or {}),
            "category": category,
        })

    def named(self, name):
        return [e for e in self.events if e["event"] == name]


@pytest.fixture
def capture(monkeypatch):
    client = _CapturingClient()
    import telemetry
    monkeypatch.setattr(telemetry, "get_telemetry_client", lambda: client)
    return client


@pytest.fixture(scope="module", autouse=True)
def _restore_event_loop():
    """``asyncio.run`` (used below) unsets the thread's event loop on exit;
    restore one so later test modules using ``get_event_loop()`` still work."""
    yield
    asyncio.set_event_loop(asyncio.new_event_loop())


def _job(**overrides):
    now = datetime.utcnow()
    defaults = dict(
        id=overrides.pop("id", 12345),
        status="completed",
        task_type="text-to-image",
        generator_name="comfy",
        model_name="flux1-dev-Q4_K_M.gguf",
        backend_name="comfy",
        generator_instance_id="tool-abc@@tab1",
        tool_id="my-comfy:my-secret-workflow",
        preset_id=None,
        parameters=json.dumps({"_run_id": "run-1"}),
        created_at=now - timedelta(seconds=10),
        started_at=now - timedelta(seconds=8),
        completed_at=now,
        error=None,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


# ── generation_pipeline_completed ───────────────────────────────────────


def test_pipeline_settles_once_per_job(capture):
    import pipeline_telemetry as pt
    job = _job(id=1001)
    pt.emit_pipeline_settled(job, "completed")
    pt.emit_pipeline_settled(job, "completed")
    events = capture.named("generation_pipeline_completed")
    assert len(events) == 1
    props = events[0]["properties"]
    assert props["status"] == "completed"
    assert props["runId"] == "run-1"
    assert props["isRetry"] is False
    assert props["source"] == "toolview"
    assert props["postprocessStepCount"] == 0
    assert props["postprocessToolRefs"] == []
    assert props["durationMs"] >= 0
    assert props["queueMs"] >= 0
    # modelFamily munged from the gguf filename, raw string never present
    assert props["modelFamily"] == "flux-1-dev"
    assert "flux1-dev-Q4_K_M" not in json.dumps(props)


def test_pipeline_user_tool_ref_is_hashed(capture):
    import pipeline_telemetry as pt
    job = _job(id=1002, tool_id="my-comfy:my-secret-workflow")
    pt.emit_pipeline_settled(job, "completed")
    props = capture.named("generation_pipeline_completed")[0]["properties"]
    # User-provider tool ids are content: only the salted hash egresses.
    assert props["toolSource"] == "user"
    assert "my-secret-workflow" not in json.dumps(props)
    assert props["toolRef"] and len(props["toolRef"]) == 16


def test_pipeline_chain_step_jobs_never_settle(capture):
    import pipeline_telemetry as pt
    from postprocessing.executor import CHAIN_INSTANCE_ID
    job = _job(id=1003, generator_instance_id=CHAIN_INSTANCE_ID)
    pt.emit_pipeline_settled(job, "completed")
    assert capture.named("generation_pipeline_completed") == []


def test_pipeline_failed_carries_error_type_and_step_index(capture):
    import pipeline_telemetry as pt
    job = _job(id=1004, error="Connection refused by provider")
    pt.emit_pipeline_settled(
        job, "failed", failed_step_index=2,
        postprocess_step_count=3,
        postprocess_tool_refs=["builtin:upscale"],
    )
    props = capture.named("generation_pipeline_completed")[0]["properties"]
    assert props["status"] == "failed"
    assert props["errorType"] == "connection_error"
    assert props["failedStepIndex"] == 2
    assert props["postprocessStepCount"] == 3
    assert props["postprocessToolRefs"] == ["builtin:upscale"]
    # Raw error text never egresses on the pipeline row.
    assert "refused" not in json.dumps(props).lower()


def test_pipeline_retry_rearms_settle_guard(capture):
    import pipeline_telemetry as pt
    job = _job(id=1005)
    pt.emit_pipeline_settled(job, "failed")
    pt.reset_for_retry(job.id)
    retried = _job(
        id=1005,
        parameters=json.dumps({"_run_id": "run-2", "_is_retry": True}),
    )
    pt.emit_pipeline_settled(retried, "completed")
    events = capture.named("generation_pipeline_completed")
    assert len(events) == 2
    assert events[1]["properties"]["isRetry"] is True
    assert events[1]["properties"]["runId"] == "run-2"


def test_pipeline_source_attribution(capture):
    import pipeline_telemetry as pt
    assert pt.job_source(_job(generator_instance_id="agent")) == "agent"
    assert pt.job_source(_job(generator_instance_id="flow")) == "flow"
    assert pt.job_source(_job(generator_instance_id="tool-x@@tab")) == "toolview"
    assert pt.job_source(_job(generator_instance_id="legacy-generate-tab")) == "toolview"


def test_pipeline_preset_hash_present_when_launched_from_preset(capture, monkeypatch):
    import pipeline_telemetry as pt
    from object_hash import salted_hash
    job = _job(id=1006, preset_id=42)
    pt.emit_pipeline_settled(job, "completed")
    props = capture.named("generation_pipeline_completed")[0]["properties"]
    assert props["presetHash"] == salted_hash("preset:42")
    assert "42" not in props["presetHash"] or len(props["presetHash"]) == 16


# ── closed errorType list + errorHash ───────────────────────────────────


def test_classify_tool_error_closed_list():
    from telemetry_props import TOOL_ERROR_TYPES, classify_tool_error
    cases = {
        "Request timeout after 30s": "timeout",
        "Job was cancelled by user": "cancelled",
        "CUDA out of memory": "out_of_memory",
        "provider not connected": "provider_disconnected",
        "WebSocket disconnected mid-job": "provider_disconnected",
        "Connection refused": "connection_error",
        "ValueError: bad params": "provider_error",
        None: "provider_error",
    }
    for message, expected in cases.items():
        result = classify_tool_error(message)
        assert result == expected, (message, result)
        assert result in TOOL_ERROR_TYPES


def test_error_hash_groups_without_content():
    from telemetry_props import error_hash
    # Same error with different numbers groups together.
    a = error_hash("Job 123 failed after 30s")
    b = error_hash("Job 456 failed after 99s")
    assert a == b
    assert len(a) == 16
    # Different errors group apart; output is hex, not the message.
    assert error_hash("something else entirely") != a
    assert "failed" not in a


# ── refusal classification -> agent_turn_completed ──────────────────────


def _make_chat(chat_id=77, flow_id=None):
    return types.SimpleNamespace(id=chat_id, flow_id=flow_id)


class _WS:
    async def broadcast(self, *a, **k):
        pass


class _Session:
    def add(self, item, *a, **k):
        # Stand in for the DB defaults a real commit would assign.
        if getattr(item, "id", None) is None:
            item.id = 1
        if getattr(item, "created_at", None) is None:
            item.created_at = datetime.utcnow()

    async def commit(self):
        pass


def _run_agent_with_stub(monkeypatch, loop_stub):
    from agent.v2 import service
    monkeypatch.setattr(service, "_run_agentic_loop", loop_stub)
    chat = _make_chat()
    asyncio.run(service.run_agent(chat, "hello", session=_Session(), ws_manager=_WS()))
    return chat


def test_agent_turn_refusal_classified_as_failed(capture, monkeypatch):
    """A turn whose final visible content is a textual refusal emits
    agent_turn_completed {status: failed, errorType: refusal}."""
    async def loop_stub(chat, session, ws_manager, max_turns, start_turn=0,
                       turn_stats=None, **kwargs):
        turn_stats["tool_call_count"] = 2
        turn_stats["last_content"] = "I cannot help with that request."

    _run_agent_with_stub(monkeypatch, loop_stub)
    events = capture.named("agent_turn_completed")
    assert len(events) == 1
    props = events[0]["properties"]
    assert props["status"] == "failed"
    assert props["errorType"] == "refusal"
    assert props["toolCallCount"] == 2
    assert props["agentContext"] == "main"
    assert "chatHash" in props and len(props["chatHash"]) == 16
    # The refusal text itself never egresses.
    assert "cannot help" not in json.dumps(props)


def test_agent_turn_normal_completion(capture, monkeypatch):
    async def loop_stub(chat, session, ws_manager, max_turns, start_turn=0,
                       turn_stats=None, **kwargs):
        turn_stats["tool_call_count"] = 1
        turn_stats["last_content"] = "Here is the image you asked for."

    _run_agent_with_stub(monkeypatch, loop_stub)
    events = capture.named("agent_turn_completed")
    assert len(events) == 1
    props = events[0]["properties"]
    assert props["status"] == "completed"
    assert "errorType" not in props


def test_agent_error_unknown_exception_maps_to_other(capture, monkeypatch):
    """The exception-class fallback is replaced by 'other' — the errorType
    domain stays closed."""
    async def loop_stub(chat, session, ws_manager, max_turns, start_turn=0,
                       turn_stats=None, **kwargs):
        raise RuntimeError("some private path /Users/nobody/secret.png")

    _run_agent_with_stub(monkeypatch, loop_stub)
    errors = capture.named("agent_error")
    assert len(errors) == 1
    props = errors[0]["properties"]
    assert props["errorType"] == "other"
    assert props["agentContext"] == "main"
    assert "chatHash" in props
    turn = capture.named("agent_turn_completed")[0]["properties"]
    assert turn["status"] == "failed"
    assert turn["errorType"] == "other"
    assert "secret" not in json.dumps(capture.events)


def test_classify_agent_error_known_members():
    from llm import QuotaExceededError, ContentFilteredError
    from llm_resolver import LLMNotConfiguredError, LLMInsufficientBalanceError
    from telemetry_props import AGENT_ERROR_TYPES, classify_agent_error
    assert classify_agent_error(ContentFilteredError("x")) == "content_filtered"
    assert classify_agent_error(LLMNotConfiguredError("x")) == "llm_not_configured"
    assert classify_agent_error(LLMInsufficientBalanceError("x")) == "insufficient_balance"
    assert classify_agent_error(asyncio.TimeoutError()) == "timeout"
    assert classify_agent_error(ValueError("anything")) == "other"
    for exc in (ContentFilteredError("x"), ValueError("y")):
        assert classify_agent_error(exc) in AGENT_ERROR_TYPES


# ── actor attribution ────────────────────────────────────────────────────


def test_set_grid_actor_values_cover_user_agent_system():
    """The three actor values each have at least one emission point wired."""
    import inspect
    import routes.media as media_routes
    from agent.v2.tools import assemble_set, assemble_grid
    import generation_queue

    media_src = inspect.getsource(media_routes)
    assert '"actor": "user"' in media_src

    agent_src = inspect.getsource(assemble_set) + inspect.getsource(assemble_grid)
    assert '"actor": "agent"' in agent_src

    queue_src = inspect.getsource(generation_queue)
    assert '"actor": "system"' in queue_src


# ── salted hash conventions ─────────────────────────────────────────────


def test_entity_hash_prefixes_are_stable_and_distinct(monkeypatch):
    import object_hash
    monkeypatch.setattr(object_hash, "_salt", "f" * 64)
    from object_hash import salted_hash
    chat = salted_hash("chat:5")
    chat_again = salted_hash("chat:5")
    board = salted_hash("board:5")
    preset = salted_hash("preset:5")
    assert chat == chat_again                # stable within an install
    assert len({chat, board, preset}) == 3   # entity types never collide
    assert all(len(h) == 16 for h in (chat, board, preset))


# ── llm_config_fields classification ────────────────────────────────────


def test_llm_config_fields_endpoint_vs_cloud(monkeypatch, capture):
    import config
    fake = types.SimpleNamespace(cloud=types.SimpleNamespace(base_url="https://cloud.example"))
    monkeypatch.setattr(config, "get_settings", lambda: fake)
    from telemetry_props import llm_config_fields

    cloud_cfg = types.SimpleNamespace(url="https://cloud.example/api/llm/v1", model="agent")
    fields = llm_config_fields(cloud_cfg)
    assert fields["llmSource"] == "stimma_cloud"
    assert "endpointClass" not in fields

    lan_cfg = types.SimpleNamespace(url="http://deepbox.local:8000/v1", model="/models/qwen3-30b-q4.gguf")
    fields = llm_config_fields(lan_cfg)
    assert fields["llmSource"] == "endpoint"
    assert fields["endpointClass"] == "lan"
    assert fields["modelFamily"] == "qwen-3"
    # The hostname and model path never appear in the output.
    assert "deepbox" not in json.dumps(fields)
    assert "gguf" not in json.dumps(fields)

    assert llm_config_fields(None) == {"llmSource": "unknown", "modelFamily": "unknown"}
