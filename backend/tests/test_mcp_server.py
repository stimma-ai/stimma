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


async def test_pinless_profile_is_open_without_ceremony(mcp_http, mcp_app):
    """No PIN, nothing to unlock: an assistant must never be told to call
    access_open first. Locking still revokes the live grant (and the work
    bound to it), but the next call is simply granted again."""
    from mcp_server.access import access

    status = body(await rpc(mcp_http, "workspace_get"))
    assert status["locked"] is False and status["requires_pin"] is False
    assert not (await rpc(mcp_http, "assets_query"))["isError"]
    before = access.unlocks["default", "one"].grant
    await rpc(mcp_http, "access_lock")
    assert not (await rpc(mcp_http, "assets_query"))["isError"]
    assert access.unlocks["default", "one"].grant != before
    # access_open stays harmless for assistants that call it anyway.
    assert body(await rpc(mcp_http, "access_open"))["locked"] is False
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app),
        base_url="http://test",
        headers=dict(mcp_http.headers),
    ) as other:
        assert body(await rpc(other, "workspace_get"))["locked"] is False
        other.headers["Authorization"] = "Bearer test-credential-two"
        assert body(await rpc(other, "workspace_get"))["locked"] is False
        assert not (await rpc(other, "assets_query"))["isError"]


async def test_synchronous_create_receipt_is_atomic_and_retryable(mcp_http):
    await rpc(mcp_http, "access_open")
    args = {
        "action": "create",
        "name": "MCP retry board",
        "request_key": "board-retry",
    }
    first = await rpc(mcp_http, "boards_update", args)
    assert not first.get("isError"), first
    second = await rpc(mcp_http, "boards_update", args)
    assert body(first) == body(second)
    conflict = await rpc(
        mcp_http, "boards_update", {**args, "name": "Changed"}
    )
    assert body(conflict)["code"] == "request_key_conflict"
    result = await rpc(
        mcp_http, "boards_get", {"action": "detail", "board_ref": body(first)["id"]}
    )
    assert not result.get("isError"), result
    assert body(result)["name"] == "MCP retry board"


async def test_query_and_catalog_schema(mcp_http):
    await rpc(mcp_http, "access_open")
    for name, args in [
        ("assets_query", {}),
        ("catalog_get", {"kind": "markers"}),
        ("projects_get", {"action": "list"}),
    ]:
        result = await rpc(mcp_http, name, args)
        assert not result.get("isError"), (name, result)
    result = await rpc(
        mcp_http,
        "projects_update",
        {
            "action": "update",
            "project_ref": "1",
            "agent_tool_config": {"allowed_tools": ["*"]},
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
    locked = await rpc(mcp_http, "assets_query")
    assert locked["isError"] and body(locked)["code"] == "profile_locked"
    assert "PIN" in body(locked)["message"]
    result = await rpc(mcp_http, "access_open", {"pin": "1234"})
    assert not body(result)["locked"]
    unlock = access.unlocks["default", "one"]
    unlock.last_activity -= 3600
    assert body(await rpc(mcp_http, "workspace_get"))["locked"]
    # Other credentials on the same PIN-protected profile unlock separately.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_http._transport.app),
        base_url="http://test",
        headers={**dict(mcp_http.headers), "Authorization": "Bearer test-credential-two"},
    ) as other:
        assert body(await rpc(other, "workspace_get"))["locked"] is True
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
    assert export["download_url"].startswith("http://test" + url + "?expires=")
    assert export["download_url"].endswith("Z")
    # The link is the credential: no Authorization header, as curl or a
    # browser would send it. A tampered link is refused.
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_http._transport.app), base_url="http://test"
    ) as anonymous:
        downloaded = await anonymous.get(url)
        assert downloaded.status_code == 200, downloaded.text
        assert downloaded.content == data.getvalue()
        assert (await anonymous.get(url[:-4] + "0000")).status_code == 403
    partial = await mcp_http.get(url, headers={"Range": "bytes=0-9"})
    assert partial.status_code == 206
    assert partial.content == data.getvalue()[:10]
    assets = body(await rpc(mcp_http, "assets_get", {"refs": [refs["asset_ref"]]}))
    # Asset details carry the link inline, so no export step is needed.
    inline = assets["items"][0]["download_url"]
    assert inline.startswith("http://test/mcp/profiles/default/download/")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_http._transport.app), base_url="http://test"
    ) as anonymous:
        assert (await anonymous.get(inline)).content == data.getvalue()
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

    schema = catalog()["assets_update"].inputSchema
    # The same schema used by the host names every action-specific field.
    result = await rpc(
        mcp_http,
        "assets_update",
        {
            "action": "markers",
            "asset_refs": [asset["asset_ref"] if "asset_ref" in asset else asset["id"]],
            "marker_ref": marker["id"],
            "add": True,
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


async def test_saved_edit_pins_revision(mcp_http):
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


@pytest.mark.asyncio
async def test_new_connection_reports_path_and_real_loopback_port(mcp_app, monkeypatch):
    """The app joins ``path`` to its own origin (the shell's proxy, which also
    reaches a remote server); ``endpoint`` must name the port actually bound,
    not the config preference the shell overrides with --port 0."""
    from core import listener

    monkeypatch.setattr(listener, "_port", 43210)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_app),
        base_url="http://test",
        headers={"X-Profile-ID": "default"},
    ) as client:
        response = await client.post("/api/mcp/clients", json={"name": "Claude Desktop"})
        assert response.status_code == 200, response.text
        connection = response.json()["connection"]
        assert connection["path"] == "/mcp/profiles/default"
        assert connection["endpoint"] == "http://127.0.0.1:43210/mcp/profiles/default"
        await client.delete(f"/api/mcp/clients/{response.json()['id']}")


async def test_tool_permission_ask_is_allow_over_mcp_and_deny_holds(mcp_http, monkeypatch):
    """The connection key is the consent: a tool that would ask in the app runs
    straight through for an MCP-driven chat. An explicit deny still blocks."""
    from types import SimpleNamespace
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from mcp_server import workspace
    from mcp_server.access import access
    from agent.v2 import tool_permission_gate
    from agent.v2.code_runtime import StimmaSDK

    descriptor = SimpleNamespace(
        parameter_schema={"type": "object", "properties": {"prompt": {"type": "string"}}},
        output_schema={},
        metadata={},
    )

    async def descriptor_for(*args):
        return "test:gated", None, descriptor

    monkeypatch.setattr(workspace, "tool_descriptor", descriptor_for)
    decision = {"value": "ask"}

    async def configured(*args, **kwargs):
        return decision["value"]

    monkeypatch.setattr(tool_permission_gate, "get_stp_permission_decision", configured)

    async def dispatch(self, tool_id, *args, **kwargs):
        await tool_permission_gate.ensure_tool_permission(
            chat_id=self.chat_id,
            tool_id=tool_id,
            kwargs=kwargs["_params_dict"],
            run_cache={},
            session_maker=async_sessionmaker(self.session.bind, expire_on_commit=False),
        )
        return {"text": "generated"}

    monkeypatch.setattr(StimmaSDK, "_dispatch_tool", dispatch)
    caller = await access.authenticate("default", "test-credential-one")

    def run(key):
        return rpc(mcp_http, "tools_run", {
            "tool_ref": access.ref(caller, "tool", "test:gated"),
            "schema_version": workspace.tool_version(descriptor),
            "parameters": {},
            "batch": [{"prompt": "a dog"}],
            "request_key": key,
        })

    result = await wait_job(mcp_http, body(await run("gated-ask")))
    assert result["state"] == "succeeded", result

    decision["value"] = "deny"
    result = await wait_job(mcp_http, body(await run("gated-deny")))
    assert result["state"] == "failed", result
    assert result["result"]["items"][0]["error"]["code"] == "forbidden"



async def test_surface_is_the_product_surface(mcp_app):
    """An assistant gets the library, generation, and organization. Not Flows,
    custom tools, chat contents, presets, saved views or public sharing."""
    from mcp_server.server import catalog

    offered = catalog()
    assert {"tools_run", "agent_start", "assets_query", "assets_update", "boards_update", "content_update", "media_export"} <= set(offered)
    for gone in ("flows_run", "flows_update", "custom_tools_update", "chat_history", "ui_context_get",
                 "share_publish", "presets_update", "saved_views_get", "assets_select", "entities_search",
                 "markers_update", "assets_trash", "containers_create"):
        assert gone not in offered, gone
    actions = lambda n: {v["properties"]["action"]["const"] for v in offered[n].inputSchema["oneOf"]}
    assert actions("boards_update") == {"create", "update", "trash", "restore", "section_create", "section_update", "section_delete", "section_reorder", "add", "remove", "move"}
    assert actions("chats_update") == {"update", "trash"}
    assert actions("projects_update") == {"create", "update"}
    assert "markers" in actions("assets_update") and "promote" not in actions("assets_update")
    for tool in offered.values():
        assert "profile_locked" not in tool.description
    assert len(offered) <= 30


async def test_tools_run_resolves_image_refs_and_names_failures(mcp_http, monkeypatch):
    """A provider image picker takes library media ids. The assistant sends the
    opaque media ref it was given; the executor must receive the id, not the
    ref, and a failing run must say why instead of "unknown outcome"."""
    import io
    from types import SimpleNamespace
    from PIL import Image
    from mcp_server import workspace
    from mcp_server.access import access
    from agent.v2.code_runtime import StimmaSDK

    image = Image.new("RGB", (8, 8), "green")
    data = io.BytesIO()
    image.save(data, format="PNG")
    upload = await mcp_http.post(
        "/mcp/profiles/default/upload",
        content=data.getvalue(),
        headers={"X-Filename": "source.png", "Content-Type": "application/octet-stream"},
    )
    media_ref = upload.json()["media_ref"]
    caller = await access.authenticate("default", "test-credential-one")
    media_id = int(access.resolve(caller, media_ref, "media"))

    descriptor = SimpleNamespace(
        parameter_schema={
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "input_images": {"type": "array", "items": {"type": "string"}, "x-control": "image_picker"},
            },
            "required": ["prompt"],
        },
        output_schema={},
        metadata={},
    )

    async def descriptor_for(*args):
        return "test:i2i", None, descriptor

    monkeypatch.setattr(workspace, "tool_descriptor", descriptor_for)
    seen = []

    async def dispatch(self, tool_id, *args, **kwargs):
        seen.append(kwargs["_params_dict"])
        raise RuntimeError("provider said: bad input at /srv/stimma/media/1.png")

    monkeypatch.setattr(StimmaSDK, "_dispatch_tool", dispatch)
    accepted = body(await rpc(mcp_http, "tools_run", {
        "tool_ref": access.ref(caller, "tool", "test:i2i"),
        "schema_version": workspace.tool_version(descriptor),
        "parameters": {"prompt": "sticker", "input_images": [media_ref]},
        "request_key": "i2i-run",
    }))
    result = await wait_job(mcp_http, accepted)
    assert seen and seen[0]["input_images"] == [media_id]
    item = result["result"]["items"][0]
    assert item["state"] == "interrupted"
    assert "provider said: bad input" in item["error"]["message"]
    assert "/srv/" not in item["error"]["message"]


async def test_upload_link_then_revise_without_a_key(mcp_http):
    """An assistant edits locally and publishes a revision: POST to the upload
    link with no key, then content_update onto the existing asset."""
    import io
    from PIL import Image

    status = body(await rpc(mcp_http, "workspace_get"))
    assert status["upload_url"].startswith("http://test/mcp/profiles/default/upload/")
    assert "expires=" in status["upload_url"]

    def png(color):
        data = io.BytesIO()
        Image.new("RGB", (8, 8), color).save(data, format="PNG")
        return data.getvalue()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=mcp_http._transport.app), base_url="http://test"
    ) as anonymous:
        first = await anonymous.post(status["upload_url"], content=png("red"), headers={"X-Filename": "v1.png"})
        assert first.status_code == 200, first.text
        second = await anonymous.post(status["upload_url"], content=png("gray"), headers={"X-Filename": "v2.png"})
        assert second.status_code == 200, second.text
        bad = await anonymous.post(status["upload_url"][:-30] + "x" * 30, content=b"x")
        assert bad.status_code in (403, 404)
    original = body(await rpc(mcp_http, "assets_get", {"refs": [first.json()["asset_ref"]]}))["items"][0]
    revised = await wait_job(mcp_http, body(await rpc(mcp_http, "content_update", {
        "format": "image",
        "source_ref": second.json()["media_ref"],
        "transforms": [],
        "target_asset_ref": first.json()["asset_ref"],
        "expected_current_revision": original["revision"]["id"],
        "note": "Desaturated locally for the print version",
        "request_key": "revise-from-upload",
    })))
    assert revised["state"] == "succeeded", revised
    assert revised["result"]["asset_ref"] == first.json()["asset_ref"]
    assert revised["result"]["revision_ref"] != original["revision"]["id"]
    # The assistant's note is the version's description and heads the lineage.
    current = body(await rpc(mcp_http, "assets_get", {"refs": [first.json()["asset_ref"]]}))["items"][0]
    assert current["revision"]["note"] == "Desaturated locally for the print version"
    assert current["media"]["generation_metadata"]["prompt"] == "Desaturated locally for the print version"
