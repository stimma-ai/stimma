"""MCP wire, profile boundary and durable retry integration tests."""

import asyncio
import hashlib
import json
import uuid
import pytest
import httpx
from sqlalchemy import select, func


@pytest.fixture(scope="module")
async def mcp_app(test_app):
    from mcp_server.server import Gateway, lifespan
    from mcp_server.settings import router
    from mcp_server.access import installation_id
    from mcp_server.models import McpClient
    from config import get_settings
    from database_registry import get_database_registry

    profile = get_settings().get_profile("default")
    profile.mcp_enabled = True
    db = get_database_registry().get_database("default")
    async with db.async_session_maker() as session:
        for name in ("one", "two"):
            session.add(
                McpClient(
                    id=name,
                    name=name,
                    credential_hash=hashlib.sha256(
                        ("test-credential-" + name).encode()
                    ).hexdigest(),
                    installation=installation_id(),
                )
            )
        await session.commit()
    test_app.include_router(router)
    test_app.mount("/mcp", Gateway())
    ready, stop = asyncio.Event(), asyncio.Event()

    async def owner():
        async with lifespan():
            ready.set()
            await stop.wait()

    task = asyncio.create_task(owner())
    await ready.wait()
    yield test_app
    stop.set()
    await task


@pytest.fixture
async def mcp_http(mcp_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app),
        base_url="http://test",
        headers={
            "Authorization": "Bearer test-credential-one",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
    ) as client:
        yield client


async def rpc(client, name, args=None):
    response = await client.post(
        "/mcp/profiles/default",
        json={
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert "result" in data, data
    return data["result"]


def body(result):
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


async def test_discovery_locked_and_actual_sdk_client(mcp_http, mcp_app):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(
        "http://test/mcp/profiles/default", http_client=mcp_http
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            assert {"agent_start", "tools_run", "boards_update", "media_export"} <= {
                t.name for t in tools.tools
            }
            result = await session.call_tool("workspace_get", {})
            assert result.structuredContent["profile_id"] == "default"


async def test_credentials_origin_profile_headers(mcp_http):
    request = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    for headers in (
        {"Authorization": "Bearer wrong"},
        {"Origin": "https://attacker.example"},
        {"X-Profile-ID": "another"},
    ):
        response = await mcp_http.post(
            "/mcp/profiles/default", json=request, headers=headers
        )
        assert response.status_code in (401, 403)
    response = await mcp_http.post("/mcp/profiles/another", json=request)
    assert response.status_code == 404


async def test_unlock_is_per_credential_and_survives_reconnect(mcp_http, mcp_app):
    await rpc(mcp_http, "access_lock")
    locked = await rpc(mcp_http, "assets_query")
    assert locked["isError"] and body(locked)["code"] == "profile_locked"
    assert body(await rpc(mcp_http, "access_open"))["locked"] is False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app),
        base_url="http://test",
        headers=dict(mcp_http.headers),
    ) as other:
        assert body(await rpc(other, "workspace_get"))["locked"] is False
        other.headers["Authorization"] = "Bearer test-credential-two"
        assert body(await rpc(other, "workspace_get"))["locked"] is True


async def test_synchronous_create_receipt_is_atomic_and_retryable(mcp_http):
    await rpc(mcp_http, "access_open")
    args = {
        "action": "create",
        "request": {"name": "MCP retry board"},
        "request_key": "board-retry",
    }
    first = await rpc(mcp_http, "boards_update", args)
    assert not first.get("isError"), first
    second = await rpc(mcp_http, "boards_update", args)
    assert body(first) == body(second)
    conflict = await rpc(
        mcp_http, "boards_update", {**args, "request": {"name": "Changed"}}
    )
    assert body(conflict)["code"] == "request_key_conflict"
    result = await rpc(
        mcp_http, "boards_get", {"action": "detail", "board_id": body(first)["id"]}
    )
    assert not result.get("isError"), result
    assert body(result)["name"] == "MCP retry board"


async def test_query_and_catalog_schema(mcp_http):
    await rpc(mcp_http, "access_open")
    for name, args in [
        ("assets_query", {}),
        ("catalog_get", {"kind": "markers"}),
        ("projects_get", {"action": "list"}),
        ("entities_search", {"q": "MCP"}),
    ]:
        result = await rpc(mcp_http, name, args)
        assert not result.get("isError"), (name, result)
    result = await rpc(
        mcp_http,
        "projects_update",
        {
            "action": "update",
            "project_id": "1",
            "request": {"agent_tool_config": {"allowed_tools": ["*"]}},
            "request_key": "bad",
        },
    )
    assert result["isError"]


async def test_unknown_fields_and_pin_not_echoed(mcp_http):
    secret = "do-not-log-this-pin"
    result = await rpc(mcp_http, "access_open", {"pin": secret, "unexpected": True})
    assert result["isError"]
    assert secret not in json.dumps(result)


async def test_pin_expiry_and_revocation(mcp_http, monkeypatch):
    from mcp_server.access import access
    from config import get_settings
    import bcrypt

    profile = get_settings().get_profile("default")
    monkeypatch.setattr(
        profile, "pin_hash", bcrypt.hashpw(b"1234", bcrypt.gensalt(rounds=4)).decode()
    )
    assert body(await rpc(mcp_http, "workspace_get"))["locked"]
    result = await rpc(mcp_http, "access_open", {"pin": "1234"})
    assert not body(result)["locked"]
    unlock = access.unlocks["default", "one"]
    unlock.last_activity -= 3600
    assert body(await rpc(mcp_http, "workspace_get"))["locked"]
    monkeypatch.setattr(profile, "pin_hash", None)


async def test_job_lost_start_response_does_not_run_twice(mcp_http, monkeypatch):
    from mcp_server import jobs

    spawned = []
    monkeypatch.setattr(jobs, "spawn", lambda *args, **kwargs: spawned.append(args))
    await rpc(mcp_http, "access_open")
    args = {"brief": "Make a cover", "request_key": "agent-retry"}
    first = await rpc(mcp_http, "agent_start", args)
    assert not first.get("isError"), first
    second = await rpc(mcp_http, "agent_start", args)
    assert body(first) == body(second)
    assert len(spawned) == 1
    recovered = await rpc(mcp_http, "jobs_get", {"job_ref": body(first)["job_ref"]})
    assert body(recovered)["state"] == "interrupted"


async def test_reference_cannot_cross_profile(mcp_http):
    from dataclasses import replace
    from mcp_server.access import access, McpError

    caller = await access.authenticate("default", "test-credential-one")
    reference = access.ref(caller, "asset", 1)
    with pytest.raises(McpError):
        access.resolve(replace(caller, profile_id="other"), reference, "asset")


async def test_agent_runtime_ids_are_profile_scoped(mcp_app):
    from agent.v2 import service
    from core.profile_context import ProfileScope

    with ProfileScope("default"):
        service._active_chat_executions.add(service._chat_key(42))
        service._mark_interrupted(42)
        assert service.is_execution_active(42)
    with ProfileScope("another"):
        assert not service.is_execution_active(42)
        assert not service._is_interrupted(42)
        assert service.get_active_chat_ids() == []
    with ProfileScope("default"):
        service._active_chat_executions.discard(service._chat_key(42))
        service._clear_interrupt(42)


async def test_upload_preview_download_range_and_relock(mcp_http):
    import io
    from PIL import Image
    from urllib.parse import quote

    image = Image.new("RGB", (12, 12), "red")
    data = io.BytesIO()
    image.save(data, format="PNG")
    await rpc(mcp_http, "access_open")
    response = await mcp_http.post(
        "/mcp/profiles/default/upload",
        content=data.getvalue(),
        headers={
            "X-Filename": "sample.png",
            "Content-Type": "application/octet-stream",
        },
    )
    assert response.status_code == 200, response.text
    refs = response.json()
    preview = await rpc(mcp_http, "media_read", {"ref": refs["media_ref"]})
    assert not preview.get("isError"), preview
    assert preview["content"][0]["type"] == "image"
    export = body(await rpc(mcp_http, "media_export", {"ref": refs["media_ref"]}))
    url = "/mcp/profiles/default/download/" + quote(export["transfer_handle"], safe="")
    downloaded = await mcp_http.get(url)
    assert downloaded.status_code == 200, downloaded.text
    assert downloaded.content == data.getvalue()
    partial = await mcp_http.get(url, headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206
    assert partial.content == data.getvalue()[:10]
    assets = body(await rpc(mcp_http, "assets_get", {"refs": [refs["asset_ref"]]}))
    assert assets["items"][0]["revision"]["id"].startswith("revision:")
    assert "file_path" not in json.dumps(assets)
    await rpc(mcp_http, "access_lock")
    assert (await mcp_http.get(url)).status_code == 403
    await rpc(mcp_http, "access_open")
    assert (await mcp_http.get(url)).status_code == 403


async def test_marker_assignment_accepts_refs(mcp_http):
    await rpc(mcp_http, "access_open")
    assets = body(await rpc(mcp_http, "assets_query"))
    assert assets["items"]
    asset = assets["items"][0]
    markers = body(await rpc(mcp_http, "catalog_get", {"kind": "markers"}))
    marker = markers["items"][0]
    from mcp_server.server import catalog

    schema = catalog()["markers_update"].inputSchema
    # The same schema used by the host names every action-specific field.
    result = await rpc(
        mcp_http,
        "markers_update",
        {
            "action": "assign",
            "request": {
                "asset_ids": [
                    asset["asset_id"] if "asset_id" in asset else asset["id"]
                ],
                "marker_id": marker["id"],
                "add": True,
            },
            "request_key": "marker-add",
        },
    )
    assert not result.get("isError"), (result, schema)


async def test_sdk_debug_logs_never_record_pin(mcp_http, caplog):
    import logging

    caplog.set_level(logging.DEBUG, logger="mcp.server.lowlevel.server")
    await rpc(mcp_http, "access_open", {"pin": "unique-sensitive-pin"})
    assert "unique-sensitive-pin" not in caplog.text


async def test_delegation_finishes_after_idle_expiry_and_reuses_chat(
    mcp_http, monkeypatch
):
    from mcp_server import jobs
    from mcp_server.access import access
    from database import ChatItem
    import agent

    calls = []

    async def fake_run(**kwargs):
        calls.append(kwargs["chat"].id)
        access.unlocks["default", "one"].last_activity -= 3600
        jobs.check_execution()
        kwargs["session"].add(
            ChatItem(
                chat_id=kwargs["chat"].id,
                item_type="assistant_message",
                message_text="Done",
            )
        )
        await kwargs["session"].commit()

    monkeypatch.setattr(agent, "run_agent", fake_run)
    await rpc(mcp_http, "access_open")
    accepted = body(
        await rpc(
            mcp_http,
            "agent_start",
            {"brief": "Test creative brief", "request_key": "finish-after-expiry"},
        )
    )
    task = jobs._tasks.get(
        (
            "default",
            access.resolve(
                await access.authenticate("default", "test-credential-one"),
                accepted["job_ref"],
                "job",
            ),
        )
    )
    if task:
        await task
    await rpc(mcp_http, "access_open")
    result = body(await rpc(mcp_http, "jobs_get", {"job_ref": accepted["job_ref"]}))
    assert result["state"] == "succeeded", result
    continued = body(
        await rpc(
            mcp_http,
            "agent_continue",
            {
                "job_ref": accepted["job_ref"],
                "controller_version": result["controller_version"],
                "message": "Refine it",
                "request_key": "follow-up",
            },
        )
    )
    await asyncio.gather(*list(jobs._tasks.values()))
    assert len(calls) == 2 and calls[0] == calls[1]
    assert continued["chat_ref"] == accepted["chat_ref"]


async def test_desktop_takeover_rejects_stale_continuation(mcp_http, monkeypatch):
    from mcp_server import jobs
    from mcp_server.access import access

    monkeypatch.setattr(jobs, "spawn", lambda *a, **k: None)
    await rpc(mcp_http, "access_open")
    job = body(
        await rpc(
            mcp_http, "agent_start", {"brief": "Handoff", "request_key": "handoff"}
        )
    )
    caller = await access.authenticate("default", "test-credential-one")
    chat_id = int(access.resolve(caller, job["chat_ref"], "chat"))
    await jobs.takeover("default", chat_id)
    result = await rpc(
        mcp_http,
        "agent_continue",
        {
            "job_ref": job["job_ref"],
            "controller_version": 1,
            "message": "Stale reply",
            "request_key": "stale-reply",
        },
    )
    assert body(result)["code"] == "control_changed"


async def wait_job(client, accepted):
    from mcp_server import jobs

    await asyncio.gather(*list(jobs._tasks.values()))
    return body(await rpc(client, "jobs_get", {"job_ref": accepted["job_ref"]}))


async def test_saved_edit_and_selection_pins_revision(mcp_http):
    await rpc(mcp_http, "access_open")
    accepted = body(
        await rpc(
            mcp_http,
            "content_update",
            {"format": "markdown", "text": "# Original", "request_key": "new-document"},
        )
    )
    first = await wait_job(mcp_http, accepted)
    assert first["state"] == "succeeded", first
    refs = first["result"]
    selected = body(await rpc(mcp_http, "assets_select", {"query": {}}))
    before = body(
        await rpc(
            mcp_http, "selections_get", {"selection_ref": selected["selection_ref"]}
        )
    )
    args = {
        "format": "markdown",
        "text": "# Revised",
        "target_asset_ref": refs["asset_ref"],
        "expected_current_revision": refs["revision_ref"],
        "request_key": "revise-document",
    }
    revised = await wait_job(
        mcp_http, body(await rpc(mcp_http, "content_update", args))
    )
    assert revised["state"] == "succeeded", revised
    assert revised["result"]["revision_ref"] != refs["revision_ref"]
    after = body(
        await rpc(
            mcp_http, "selections_get", {"selection_ref": selected["selection_ref"]}
        )
    )
    assert before == after
    args.update(text="# Stale", request_key="stale-revision")
    conflict = await wait_job(
        mcp_http, body(await rpc(mcp_http, "content_update", args))
    )
    assert (
        conflict["state"] == "failed"
        and conflict["result"]["code"] == "revision_conflict"
    ), conflict


async def test_unknown_provider_outcome_is_retained_and_not_retried(
    mcp_http, monkeypatch
):
    from types import SimpleNamespace
    from mcp_server import workspace
    from mcp_server.access import access
    from agent.v2.code_runtime import StimmaSDK

    descriptor = SimpleNamespace(
        parameter_schema={
            "type": "object",
            "properties": {"prompt": {"type": "string"}},
        },
        output_schema={},
        metadata={},
    )

    async def descriptor_for(*args):
        return "test:fake", None, descriptor

    monkeypatch.setattr(workspace, "tool_descriptor", descriptor_for)
    calls = []

    async def dispatch(self, *args, **kwargs):
        calls.append(kwargs["_params_dict"]["prompt"])
        if len(calls) == 2:
            raise TimeoutError("provider may have finished")
        return {"text": "confirmed result"}

    monkeypatch.setattr(StimmaSDK, "_dispatch_tool", dispatch)
    await rpc(mcp_http, "access_open")
    caller = await access.authenticate("default", "test-credential-one")
    accepted = body(
        await rpc(
            mcp_http,
            "tools_run",
            {
                "tool_ref": access.ref(caller, "tool", "test:fake"),
                "schema_version": workspace.tool_version(descriptor),
                "parameters": {},
                "batch": [
                    {"prompt": "first"},
                    {"prompt": "second"},
                    {"prompt": "third"},
                ],
                "request_key": "unknown-batch",
            },
        )
    )
    result = await wait_job(mcp_http, accepted)
    assert result["state"] == "failed", result
    assert [i["state"] for i in result["result"]["items"]] == [
        "succeeded",
        "interrupted",
    ]
    retry = await rpc(
        mcp_http,
        "jobs_retry",
        {"job_ref": accepted["job_ref"], "request_key": "retry-unknown"},
    )
    assert body(retry)["code"] == "retry_unavailable"
    assert calls == ["first", "second"]


async def test_stdio_bridge_roundtrip_and_private_install(
    mcp_app, tmp_path, monkeypatch, capsys
):
    import os, socket, sys
    import uvicorn
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp_server.bridge import install, config_path
    from mcp_server.access import installation_id
    from mcp_server.models import McpClient
    from database_registry import get_database_registry

    credential = "test-only-bridge-credential-with-sufficient-length"
    async with (
        get_database_registry().get_database("default").async_session_maker() as session
    ):
        session.add(
            McpClient(
                id="bridge-test",
                name="Bridge test",
                credential_hash=hashlib.sha256(credential.encode()).hexdigest(),
                installation=installation_id(),
            )
        )
        await session.commit()
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    config = {
        "alias": "test",
        "credential": credential,
        "endpoint": f"http://127.0.0.1:{port}/mcp/profiles/default",
        "download_directory": str(tmp_path / "downloads"),
    }
    bootstrap = tmp_path / "connection.json"
    bootstrap.write_text(json.dumps(config))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    install(bootstrap)
    assert config_path("test").stat().st_mode & 0o777 == 0o600
    assert credential not in capsys.readouterr().out
    server = uvicorn.Server(
        uvicorn.Config(mcp_app, lifespan="off", access_log=False, log_level="error")
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server.bridge", "bridge", "test"],
            env=dict(os.environ),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                names = {t.name for t in (await client.list_tools()).tools}
                assert {"media_upload", "media_download", "agent_start"} <= names
                opened = await client.call_tool("access_open", {})
                assert not opened.isError
                from PIL import Image

                source = tmp_path / "bridge.png"
                Image.new("RGB", (4, 4), "blue").save(source)
                uploaded = await client.call_tool("media_upload", {"path": str(source)})
                assert not uploaded.isError, uploaded
                downloaded = await client.call_tool(
                    "media_download", {"ref": uploaded.structuredContent["media_ref"]}
                )
                assert not downloaded.isError, downloaded
                from pathlib import Path

                assert (
                    Path(downloaded.structuredContent["path"]).read_bytes()
                    == source.read_bytes()
                )
    finally:
        server.should_exit = True
        await task
        listener.close()


async def test_ui_selection_requires_explicit_share_and_lock_clears_it(mcp_http):
    from mcp_server.access import access

    await rpc(mcp_http, "access_open")
    assert not body(await rpc(mcp_http, "ui_context_get"))["shared"]
    item = body(await rpc(mcp_http, "assets_query"))["items"][0]
    reference = item.get("asset_id") or item["id"]
    caller = await access.authenticate("default", "test-credential-one")
    identifier = int(access.resolve(caller, reference, "asset"))
    response = await mcp_http.post(
        "/api/mcp/context",
        json={"asset_ids": [identifier]},
        headers={"X-Profile-ID": "default"},
    )
    assert response.status_code == 200, response.text
    shared = body(await rpc(mcp_http, "ui_context_get"))
    assert shared["shared"] and shared["targets"][0]["asset_ref"] == reference
    await mcp_http.post("/api/mcp/lock", headers={"X-Profile-ID": "default"})
    await rpc(mcp_http, "access_open")
    assert not body(await rpc(mcp_http, "ui_context_get"))["shared"]


async def test_flow_runs_real_scalar_program(mcp_http, monkeypatch):
    from mcp_server import workspace

    original = workspace.execute_flow
    errors = []

    async def capture(*args):
        try:
            return await original(*args)
        except Exception as exc:
            errors.append(repr(exc))
            raise

    monkeypatch.setattr(workspace, "execute_flow", capture)
    from core.profile_context import ProfileScope
    from database import Flow
    from database_registry import get_database_registry
    from flow_runtime import create_flow_directory, get_flow_program_path
    from mcp_server.access import access

    program = """from stimma.flow import flow, output, code, phase
@flow(name="MCP scalar", outputs={"result": output("str")})
def program():
    with phase("Greeting"):
        return code(lambda: "Hello from Flow", inputs={}, output_type="text")
"""
    caller = await access.authenticate("default", "test-credential-one")
    with ProfileScope("default"):
        async with (
            get_database_registry()
            .get_database("default")
            .async_session_maker() as session
        ):
            flow = Flow(name="MCP scalar")
            session.add(flow)
            await session.flush()
            create_flow_directory(flow.id)
            get_flow_program_path(flow.id).write_text(program)
            await session.commit()
            ref = access.ref(caller, "flow", flow.id)
    await rpc(mcp_http, "access_open")
    started = body(
        await rpc(
            mcp_http,
            "flows_run",
            {
                "flow_ref": ref,
                "program_version": hashlib.sha256(program.encode()).hexdigest(),
                "request_key": "scalar-flow",
            },
        )
    )
    result = await wait_job(mcp_http, started)
    assert result["state"] == "succeeded", (result, errors)
    assert not errors, errors
    assert result["result"]["outputs"] == [
        {"name": "result", "value": "Hello from Flow"}
    ]


async def test_second_profile_database_and_custom_tool_cache_are_isolated(
    mcp_http, tmp_path, monkeypatch
):
    from config import get_settings, ProfileConfig
    from core.profile_context import ProfileScope
    from database import Board
    from database_registry import get_database_registry
    from mcp_server.access import access, installation_id
    from mcp_server.models import McpClient
    from providers.user_tools import UserToolsProvider
    from providers.registry import ProviderRegistry

    settings = get_settings()
    other = ProfileConfig(
        id="mcp-other",
        name="Other",
        database=str(tmp_path / "other.db"),
        mcp_enabled=True,
    )
    monkeypatch.setattr(settings, "profiles", [*settings.profiles, other])
    registry = get_database_registry()
    registry.register_profile(other)
    try:
        with ProfileScope(other.id):
            from utils.migrations import run_all_migrations

            run_all_migrations()
            await registry.init_database(other.id)
            async with registry.get_database(other.id).async_session_maker() as session:
                session.add(
                    McpClient(
                        id="one",
                        name="Other connection",
                        credential_hash=hashlib.sha256(
                            b"other-profile-credential"
                        ).hexdigest(),
                        installation=installation_id(),
                    )
                )
                session.add(Board(id=1, name="Other profile board"))
                await session.commit()
        unauthorized = await mcp_http.post(
            "/mcp/profiles/mcp-other",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert unauthorized.status_code == 401
        caller = await access.authenticate("default", "test-credential-one")
        other_caller = await access.authenticate(other.id, "other-profile-credential")
        from mcp_server.access import McpError

        with pytest.raises(McpError):
            access.resolve(other_caller, access.ref(caller, "board", 1), "board")
        provider = UserToolsProvider()
        catalog = ProviderRegistry()
        from types import SimpleNamespace

        descriptor = SimpleNamespace(id="same-id", name="Private tool")

        async def no_cache(*args):
            pass

        monkeypatch.setattr(catalog, "_cache_tools_to_db", no_cache)
        with ProfileScope("default"):
            provider._state()["loaded"] = True
            provider._descriptors = {"same-id": descriptor}
            await catalog._refresh_tools_for_provider(provider)
            assert catalog.get_tool("user-tools:same-id")[1] is descriptor
        with ProfileScope(other.id):
            assert await provider.list_tools() == []
            await catalog._refresh_tools_for_provider(provider)
            assert catalog.get_tool("user-tools:same-id") is None
        with ProfileScope("default"):
            assert catalog.get_tool("user-tools:same-id")[1] is descriptor
        catalog._profile_tools.pop("default", None)
        catalog._profile_tools.pop(other.id, None)
    finally:
        await registry.unregister_profile(other.id)


async def test_atomic_mutation_broadcasts_only_after_commit(mcp_http):
    from mcp_server.access import access
    from mcp_server.jobs import mutate
    from utils.websocket import WebSocketManager
    from database import Board
    from database_registry import get_database_registry
    from core.profile_context import ProfileScope

    caller = await access.authenticate("default", "test-credential-one")
    db = get_database_registry().get_database("default")
    manager = WebSocketManager()
    delivered = []

    class Receiver:
        async def send_text(self, message):
            async with db.async_session_maker() as session:
                delivered.append(
                    await session.scalar(
                        select(Board.name).where(
                            Board.id == json.loads(message)["data"]["board_id"]
                        )
                    )
                )

    manager.active_connections.append(Receiver())

    async def change(session):
        board = Board(name="Committed before broadcast")
        session.add(board)
        await session.commit()
        await manager.broadcast("board_created", {"board_id": board.id})
        assert delivered == []
        return {"created": True}

    with ProfileScope("default"):
        await mutate(caller, "test_broadcast", "receipt-with-broadcast", {}, change)
    assert delivered == ["Committed before broadcast"]


async def test_flow_selection_waits_for_exact_response(mcp_http, monkeypatch):
    from mcp_server import workspace

    original = workspace.execute_flow
    errors = []

    async def capture(*args):
        try:
            return await original(*args)
        except Exception as exc:
            errors.append(repr(exc))
            raise

    monkeypatch.setattr(workspace, "execute_flow", capture)
    from core.profile_context import ProfileScope
    from database import Flow
    from database_registry import get_database_registry
    from flow_runtime import create_flow_directory, get_flow_program_path
    from mcp_server.access import access
    from mcp_server import jobs

    program = """from stimma.flow import flow, output, code, phase, hitl
@flow(name="MCP selection", outputs={"result": output("str")})
def program():
    with phase("Choose"):
        candidates = code(lambda: ["first", "second"], inputs={}, output_type="list[str]")
        return hitl.select(candidates, count=1, instructions="Choose the second option")
"""
    caller = await access.authenticate("default", "test-credential-one")
    with ProfileScope("default"):
        async with (
            get_database_registry()
            .get_database("default")
            .async_session_maker() as session
        ):
            flow = Flow(name="MCP selection")
            session.add(flow)
            await session.flush()
            create_flow_directory(flow.id)
            get_flow_program_path(flow.id).write_text(program)
            await session.commit()
            ref = access.ref(caller, "flow", flow.id)
    await rpc(mcp_http, "access_open")
    accepted = body(
        await rpc(
            mcp_http,
            "flows_run",
            {
                "flow_ref": ref,
                "program_version": hashlib.sha256(program.encode()).hexdigest(),
                "request_key": "flow-choice",
            },
        )
    )
    try:
        async with asyncio.timeout(5):
            while True:
                result = body(
                    await rpc(mcp_http, "jobs_get", {"job_ref": accepted["job_ref"]})
                )
                assert result["state"] not in ("succeeded", "failed"), errors
                if result["state"] == "input_required":
                    break
                await asyncio.sleep(0.01)
        history = body(
            await rpc(mcp_http, "chat_history", {"chat_ref": accepted["chat_ref"]})
        )
        assert history["items"] and history["items"][-1]["type"] == "hitl_request"
        args = {
            "job_ref": accepted["job_ref"],
            "controller_version": result["controller_version"],
            "interaction_ref": result["interaction"]["ref"],
            "version": 1,
            "response": {"choice_indices": [1]},
            "request_key": "choose-second",
        }
        response = await rpc(mcp_http, "interaction_respond", args)
        assert not response.get("isError"), response
        assert body(await rpc(mcp_http, "interaction_respond", args)) == body(response)
        result = await wait_job(mcp_http, accepted)
        assert result["state"] == "succeeded", result
        assert result["result"]["outputs"][0]["value"] == "second"
        args["request_key"] = "stale-question"
        assert (
            body(await rpc(mcp_http, "interaction_respond", args))["code"]
            == "control_changed"
        )
    finally:
        for task in list(jobs._tasks.values()):
            task.cancel()
        await asyncio.gather(*list(jobs._tasks.values()), return_exceptions=True)


async def test_flow_candidate_preview_is_temporary_and_read_only(mcp_http):
    from mcp_server.workspace import flow_candidate
    from mcp_server.access import access
    from database import MediaItem
    from database_registry import get_database_registry
    from flow_dsl.shapes import Scalar
    from PIL import Image
    import io

    data = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(data, format="PNG")
    await rpc(mcp_http, "access_open")
    uploaded = (
        await mcp_http.post(
            "/mcp/profiles/default/upload",
            content=data.getvalue(),
            headers={"X-Filename": "candidate.png"},
        )
    ).json()
    caller = await access.authenticate("default", "test-credential-one")
    async with (
        get_database_registry().get_database("default").async_session_maker() as session
    ):
        media = await session.get(
            MediaItem, int(access.resolve(caller, uploaded["media_ref"], "media"))
        )
        media.ephemeral_run_id = "test-candidate-run"
        await session.commit()
        try:
            candidate = await flow_candidate(caller, media.id, Scalar("media"), session)
            result = await rpc(
                mcp_http, "media_read", {"ref": candidate["preview_ref"]}
            )
            assert (
                not result.get("isError") and result["content"][0]["type"] == "image"
            ), result
            assert (
                await rpc(mcp_http, "media_export", {"ref": candidate["preview_ref"]})
            )["isError"]
            # Reusing a payload for another run cannot reuse this preview authority.
            media.ephemeral_run_id = "different-run"
            await session.commit()
            assert (
                await rpc(mcp_http, "media_read", {"ref": candidate["preview_ref"]})
            )["isError"]
        finally:
            media.ephemeral_run_id = None
            await session.commit()
