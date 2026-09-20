"""MCP wire, profile boundary and durable retry integration tests."""

import asyncio
import hashlib
import json
import uuid
import pytest
import httpx
from sqlalchemy import select, func


@pytest.fixture
async def direct_http(mcp_app, monkeypatch):
    import socket
    from types import SimpleNamespace
    from config import McpDirectConfig
    from mcp_server import listener as transport

    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    config = McpDirectConfig(enabled=True, port=port)
    monkeypatch.setattr(transport, 'get_settings', lambda: SimpleNamespace(mcp_direct=config))
    instance = transport.DirectListener()
    async with instance.lifespan():
        assert instance.status('default')['status'] == 'listening'
        async with httpx.AsyncClient(
            base_url=f'http://127.0.0.1:{port}', trust_env=False,
            headers={'Authorization': 'Bearer test-credential-one',
                     'Accept': 'application/json, text/event-stream',
                     'MCP-Protocol-Version': '2025-11-25'},
        ) as client:
            yield client, instance, config


@pytest.mark.asyncio(loop_scope="module")
async def test_direct_mcp_wire_transfers_and_revocation(direct_http, monkeypatch):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from config import get_settings

    client, instance, config = direct_http
    async with streamable_http_client(str(client.base_url) + '/mcp/profiles/default', http_client=client) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert (await session.list_tools()).tools
    # Forwarded headers must not poison returned transfer URLs.
    client.headers.update({'X-Forwarded-Host': 'attacker.invalid', 'X-Forwarded-Proto': 'https'})
    workspace = body(await rpc(client, 'workspace_get'))
    assert workspace['upload_url'].startswith(str(client.base_url))
    payload = product_image_bytes('blue')
    async with httpx.AsyncClient(trust_env=False) as anonymous:
        uploaded = await anonymous.post(workspace['upload_url'], content=payload, headers={'X-Filename': 'direct.png'})
        assert uploaded.status_code == 200, uploaded.text
        result = body(await rpc(client, 'media_export', {'ref': uploaded.json()['media_ref']}))
        assert result['download_url'].startswith(str(client.base_url))
        download = await anonymous.get(result['download_url'])
        assert download.content == payload
        partial = await anonymous.get(result['download_url'], headers={'Range': 'bytes=0-7'})
        assert partial.status_code == 206
        assert partial.content == payload[:8]
        await rpc(client, 'access_lock')
        assert (await anonymous.get(result['download_url'])).status_code == 403
        assert (await anonymous.post(workspace['upload_url'], content=payload)).status_code == 403
    profile = get_settings().get_profile('default')
    monkeypatch.setattr(profile, 'mcp_enabled', False)
    response = await client.post('/mcp/profiles/default', json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'})
    assert response.status_code == 404


@pytest.mark.asyncio(loop_scope="module")
async def test_direct_surface_host_auth_and_maintenance(direct_http, monkeypatch):
    import headless_runtime
    client, _, _ = direct_http
    for path in ('/api/settings', '/api/mcp/settings', '/api/headless/mcp', '/multi-device/session', '/', '/mcp/profiles/default/other'):
        assert (await client.get(path)).status_code == 404
    request = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'}
    path = '/mcp/profiles/default'
    for headers, status in (
        ({'Authorization': ''}, 401),
        ({'Authorization': 'Bearer wrong'}, 401),
        ({'Host': 'attacker.invalid'}, 403),
        ({'Origin': 'https://attacker.invalid'}, 403),
        ({'X-Profile-Id': 'another'}, 403),
    ):
        assert (await client.post(path, json=request, headers=headers)).status_code == status
    assert (await client.post('/mcp/profiles/another', json=request)).status_code == 404
    monkeypatch.setattr(headless_runtime, '_maintenance', True)
    assert (await client.post(path, json=request)).status_code == 503


@pytest.mark.asyncio(loop_scope="module")
async def test_direct_restart_disable_and_port_collision(direct_http):
    import socket
    client, instance, config = direct_http
    old_port = config.port
    config.enabled = False
    await instance.apply()
    assert instance.status('default')['endpoint'] is None
    with pytest.raises(httpx.ConnectError):
        await client.get('/mcp/profiles/default')
    with socket.socket() as occupied:
        occupied.bind(('127.0.0.1', 0))
        occupied.listen()
        config.enabled = True
        config.port = occupied.getsockname()[1]
        await instance.apply()
        assert instance.status('default')['status'] == 'error'
        assert 'Port already in use' in instance.error
        assert instance.status('default')['endpoint'] is None
    config.port = old_port
    await instance.apply()
    assert instance.status('default')['status'] == 'listening'
    assert not (await rpc(client, 'workspace_get')).get('isError')


async def test_direct_settings_validation_and_persistence(mcp_app):
    from mcp_server.listener import listener
    from config import get_settings, reload_settings
    from config_writer import patch_global_section
    saved = get_settings().mcp_direct.model_dump()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp_app), base_url='http://test', headers={'X-Profile-ID': 'default'}) as client:
            for bad in ({'host': '0.0.0.0'}, {'host': '::'}, {'host': '::ffff:0.0.0.0'}, {'host': 'example.com'}, {'port': 0}, {'port': 65536}):
                assert (await client.put('/api/mcp/direct', json=bad)).status_code == 422
            result = await client.put('/api/mcp/direct', json={'enabled': False, 'host': '127.0.0.1', 'port': 19294})
            assert result.status_code == 200
            assert reload_settings().mcp_direct.port == 19294
            settings = (await client.get('/api/mcp/settings')).json()
            assert settings['direct']['status'] == 'off'
            assert any(item['host'] == '127.0.0.1' for item in settings['addresses'])
    finally:
        patch_global_section('mcp_direct', saved)
        reload_settings()
        get_settings().get_profile('default').mcp_enabled = True
        await listener.apply()


async def test_headless_mcp_setup_without_desktop(mcp_app, monkeypatch):
    from fastapi import FastAPI
    import headless_runtime
    from config import get_settings

    app = FastAPI()
    app.include_router(headless_runtime.router)
    monkeypatch.setattr(headless_runtime, 'ENABLED', True)
    monkeypatch.setenv('STIMMA_SUPERVISOR_TOKEN', 'owner-secret')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        assert (await client.post('/api/headless/mcp', json={})).status_code == 403
        client.headers['X-Stimma-Supervisor'] = 'owner-secret'
        assert (await client.post('/api/headless/mcp', json={'profile': 'missing'})).status_code == 404
        status = (await client.post('/api/headless/mcp', json={})).json()
        assert status['profile_id'] == 'default'
        assert {'id': 'default', 'name': get_settings().get_profile('default').name} in status['profiles']
        assert (await client.post('/api/headless/mcp', json={'command': 'enable'})).status_code == 200
        created = await client.post('/api/headless/mcp', json={'command': 'connect', 'name': 'Headless agent'})
        assert created.status_code == 200
        connection = created.json()['connection']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp_app), base_url='http://test', headers={
            'Authorization': f"Bearer {connection['credential']}", 'Accept': 'application/json, text/event-stream',
        }) as agent:
            assert body(await rpc(agent, 'workspace_get'))['profile_id'] == 'default'
        assert (await client.post('/api/headless/mcp', json={'command': 'disable'})).status_code == 200
        assert (await client.post('/api/headless/mcp', json={'command': 'connect'})).status_code == 409
        await client.post('/api/headless/mcp', json={'command': 'enable'})


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
    """Creative documents are available through content families alongside generation."""
    from mcp_server.server import catalog

    offered = catalog()
    assert {"tools_run", "agent_start", "assets_query", "assets_update", "boards_update", "content_update", "content_get", "media_export"} <= set(offered)
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


def product_image_bytes(color="red", format="JPEG"):
    import io
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (24, 16), color).save(stream, format=format)
    return stream.getvalue()


async def product_upload(client, data, filename="product.jpg", staged=False):
    status = body(await rpc(client, "workspace_get"))
    response = await client.post(status["upload_url"], content=data, headers={
        "X-Filename": filename, "X-Stimma-Stage": str(staged).lower(),
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize("kind", ["jpeg", "wav"])
async def test_external_file_roundtrip_preserves_bytes_lineage_and_asset_count(mcp_http, kind, monkeypatch):
    import io
    import wave
    from database import Asset, MediaLineage, MediaOwner, MediaItem
    from database_registry import get_database_registry
    from mcp_server.access import access

    first = await product_upload(mcp_http, product_image_bytes("red"))
    second = await product_upload(mcp_http, product_image_bytes("blue"))
    data = product_image_bytes("purple")
    if kind == "wav":
        # This tests preservation of extracted metadata, not ffprobe itself.
        # Backend CI deliberately runs without the optional media executables.
        monkeypatch.setattr("media_scanner.get_audio_metadata", lambda path: {
            "sample_rate": 8000, "channels": 1, "duration": 0.1,
        })
        stream = io.BytesIO()
        with wave.open(stream, "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b"\x00\x01" * 800)
        data = stream.getvalue()
    db = get_database_registry().get_database("default")
    async with db.async_session_maker() as session:
        count = await session.scalar(select(func.count()).select_from(Asset))
    staged = await product_upload(mcp_http, data, f"external.{kind}", staged=True)
    assert "asset_ref" not in staged
    async with db.async_session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == count
    args = {
        "format": "file", "source_ref": staged["media_ref"],
        "source_refs": [first["media_ref"], second["media_ref"]],
        "note": "Combined two campaign references externally",
        "request_key": f"external-{kind}",
    }
    saved = await wait_job(mcp_http, body(await rpc(mcp_http, "content_update", args)))
    assert saved["state"] == "succeeded", saved
    refs = saved["result"]
    link = body(await rpc(mcp_http, "media_export", {"ref": refs["media_ref"]}))
    downloaded = await mcp_http.get(link["download_url"])
    assert downloaded.content == data
    assert downloaded.headers["x-content-sha256"] == staged["sha256"]
    detail = body(await rpc(mcp_http, "assets_get", {"refs": [refs["asset_ref"]]}))["items"][0]
    assert detail["media"]["file_format"] == kind
    assert detail["revision"]["note"] == args["note"]
    caller = await access.authenticate("default", "test-credential-one")
    mid = int(access.resolve(caller, refs["media_ref"], "media"))
    uploaded_mid = int(access.resolve(caller, staged["media_ref"], "media"))
    async with db.async_session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == count + 1
        parents = list(await session.scalars(select(MediaLineage.source_media_id).where(
            MediaLineage.media_id == mid,
        ).order_by(MediaLineage.source_order)))
        assert parents == [int(access.resolve(caller, item["media_ref"], "media")) for item in (first, second)]
        assert await session.scalar(select(MediaOwner.id).where(
            MediaOwner.media_id == uploaded_mid, MediaOwner.root_kind == "upload", MediaOwner.deleted_at.is_(None),
        )) is None
        saved_media = await session.get(MediaItem, mid)
        uploaded_media = await session.get(MediaItem, uploaded_mid)
        assert saved_media.storage_object_id == uploaded_media.storage_object_id
        if kind == "wav":
            assert saved_media.audio_sample_rate == 8000
            assert saved_media.audio_channels == 1
            assert saved_media.duration == uploaded_media.duration
    duplicate = body(await rpc(mcp_http, "content_update", args))
    assert duplicate["job_ref"] == saved["job_ref"]

    replacement = await product_upload(mcp_http, data, f"revision.{kind}", staged=True)
    revision_args = {**args, "source_ref": replacement["media_ref"],
        "target_asset_ref": refs["asset_ref"], "expected_current_revision": refs["revision_ref"],
        "request_key": f"external-revision-{kind}"}
    revised = await wait_job(mcp_http, body(await rpc(mcp_http, "content_update", revision_args)))
    assert revised["state"] == "succeeded", revised
    assert revised["result"]["asset_ref"] == refs["asset_ref"]
    async with db.async_session_maker() as session:
        assert await session.scalar(select(func.count()).select_from(Asset)) == count + 1
    conflict_upload = await product_upload(mcp_http, data, f"conflict.{kind}", staged=True)
    conflict = await wait_job(mcp_http, body(await rpc(mcp_http, "content_update", {
        **revision_args, "source_ref": conflict_upload["media_ref"], "request_key": f"external-conflict-{kind}",
    })))
    assert conflict["result"]["code"] == "revision_conflict", conflict
    async with db.async_session_maker() as session:
        assert await session.scalar(select(MediaOwner.id).where(
            MediaOwner.media_id == int(access.resolve(caller, conflict_upload["media_ref"], "media")),
            MediaOwner.root_kind == "upload", MediaOwner.deleted_at.is_(None),
        )) is not None


async def test_image_transforms_record_exact_operations(mcp_http):
    uploaded = await product_upload(mcp_http, product_image_bytes())
    transforms = [{"action": "crop", "box": [0, 0, 12, 16]}, {"action": "rotate", "degrees": 90}]
    result = await wait_job(mcp_http, body(await rpc(mcp_http, "content_update", {
        "format": "image", "source_ref": uploaded["media_ref"], "transforms": transforms,
        "note": "Cropped and rotated for the placement", "request_key": "transform-provenance",
    })))
    assert result["state"] == "succeeded", result
    item = body(await rpc(mcp_http, "assets_get", {"refs": [result["result"]["asset_ref"]]}))["items"][0]
    assert (item["media"]["width"], item["media"]["height"]) == (16, 12)
    assert item["media"]["generation_metadata"]["parameters"]["transforms"] == transforms


async def test_five_country_batch_retry_and_external_edit(mcp_http, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from PIL import Image
    from agent.v2.code_runtime import StimmaSDK, ToolResult
    from agent.v2.tool_permission_gate import ToolPermissionDenied
    from mcp_server import workspace
    from mcp_server.access import access

    countries = ["France", "Germany", "Japan", "Canada", "Brazil"]
    descriptor = SimpleNamespace(parameter_schema={"type": "object", "properties": {"prompt": {"type": "string"}}}, output_schema={}, metadata={})
    async def descriptor_for(*args):
        return "test:country-ad", None, descriptor
    monkeypatch.setattr(workspace, "tool_descriptor", descriptor_for)
    calls = []
    async def dispatch(self, tool_id, **kwargs):
        params = kwargs["_params_dict"]
        assert set(params) == {"prompt"}
        country = params["prompt"]
        calls.append(country)
        if country == "Japan" and calls.count(country) == 1:
            raise ToolPermissionDenied("Permission denied before dispatch")
        path = tmp_path / f"{country}.png"
        Image.new("RGB", (24, 16), "green").save(path)
        return ToolResult(path=path, tool_name=tool_id, parameters=params)
    monkeypatch.setattr(StimmaSDK, "_dispatch_tool", dispatch)
    caller = await access.authenticate("default", "test-credential-one")
    args = {"tool_ref": access.ref(caller, "tool", "test:country-ad"),
        "schema_version": workspace.tool_version(descriptor), "parameters": {},
        "batch": [{"prompt": country} for country in countries], "batch_labels": countries,
        "request_key": "five-country-smoke"}
    invalid = body(await rpc(mcp_http, "tools_run", {**args, "batch_labels": ["France"]}))
    assert invalid["code"] == "invalid_arguments"
    assert calls == []
    result = await wait_job(mcp_http, body(await rpc(mcp_http, "tools_run", args)))
    assert result["state"] == "failed", result
    items = result["result"]["items"]
    assert [item["label"] for item in items] == countries
    assert [item["state"] for item in items] == ["succeeded", "succeeded", "failed", "succeeded", "succeeded"]
    retried = await wait_job(mcp_http, body(await rpc(mcp_http, "jobs_retry", {
        "job_ref": result["job_ref"], "request_key": "five-country-retry",
    })))
    assert retried["state"] == "succeeded", retried
    assert calls == countries + ["Japan"]
    retry_item = retried["result"]["items"][0]
    assert (retry_item["label"], retry_item["original_index"]) == ("Japan", 2)
    assert retried["result"]["retry_of"] == result["job_ref"]
    source = items[0]["output"]
    original = await mcp_http.get(body(await rpc(mcp_http, "media_export", {"ref": source["media_ref"]}))["download_url"])
    import io
    with Image.open(io.BytesIO(original.content)) as image:
        edited = io.BytesIO()
        image.resize((48, 32)).save(edited, format="JPEG")
    upload = await product_upload(mcp_http, edited.getvalue(), "France-banner.jpg", staged=True)
    saved = await wait_job(mcp_http, body(await rpc(mcp_http, "content_update", {
        "format": "file", "source_ref": upload["media_ref"], "source_refs": [source["media_ref"]],
        "note": "Prepared France placement externally", "request_key": "five-country-save",
    })))
    assert saved["state"] == "succeeded", saved
    final_file = await mcp_http.get(body(await rpc(mcp_http, "media_export", {"ref": saved["result"]["media_ref"]}))["download_url"])
    assert final_file.content == edited.getvalue()


async def test_delegated_receipt_excludes_intermediates_and_resets_on_followup(mcp_http, monkeypatch):
    import agent
    from database import ChatItem
    from mcp_server.access import access

    first = await product_upload(mcp_http, product_image_bytes("red"))
    second = await product_upload(mcp_http, product_image_bytes("blue"))
    caller = await access.authenticate("default", "test-credential-one")
    mids = [int(access.resolve(caller, item["media_ref"], "media")) for item in (first, second)]
    calls = 0
    async def fake_run(**kwargs):
        nonlocal calls
        session, chat = kwargs["session"], kwargs["chat"]
        assert "unmet requirements" in kwargs["user_message"]
        if calls == 0:
            session.add(ChatItem(chat_id=chat.id, item_type="media_display", show_role="intermediate", media_ids=json.dumps([mids[1]])))
            session.add(ChatItem(chat_id=chat.id, item_type="media_display", show_role="final", media_ids=json.dumps([mids[0]])))
            summary = "France is ready. Germany could not be finished."
        else:
            session.add(ChatItem(chat_id=chat.id, item_type="media_display", show_role="final", media_ids=json.dumps([mids[1]])))
            summary = "Germany is now ready."
        session.add(ChatItem(chat_id=chat.id, item_type="assistant_message", message_text=summary))
        calls += 1
        await session.commit()
    monkeypatch.setattr(agent, "run_agent", fake_run)
    result = await wait_job(mcp_http, body(await rpc(mcp_http, "agent_start", {
        "brief": "Make localized ads", "deliverables": {"count": 2}, "request_key": "delegated-receipt",
    })))
    assert result["state"] == "succeeded", result
    receipt = result["result"]
    assert [item["media_ref"] for item in receipt["outputs"]] == [first["media_ref"]]
    assert receipt["summary"] == "France is ready. Germany could not be finished."
    assert receipt["shortfalls"] == ["Requested 2 outputs; the agent marked 1 final."]
    continued = await wait_job(mcp_http, body(await rpc(mcp_http, "agent_continue", {
        "job_ref": result["job_ref"], "controller_version": result["controller_version"],
        "message": "Finish Germany", "request_key": "delegated-receipt-followup",
    })))
    assert continued["state"] == "succeeded", continued
    assert [item["media_ref"] for item in continued["result"]["outputs"]] == [second["media_ref"]]
    assert continued["result"]["shortfalls"] == []


async def test_delegated_failure_retains_final_outputs(mcp_http, monkeypatch):
    import agent
    from database import ChatItem
    from mcp_server.access import access

    uploaded = await product_upload(mcp_http, product_image_bytes())
    caller = await access.authenticate("default", "test-credential-one")
    mid = int(access.resolve(caller, uploaded["media_ref"], "media"))

    async def fake_run(**kwargs):
        kwargs["session"].add(ChatItem(
            chat_id=kwargs["chat"].id, item_type="media_display",
            show_role="final", media_ids=json.dumps([mid]),
        ))
        await kwargs["session"].commit()
        raise RuntimeError("simulated interruption after saving the first output")

    monkeypatch.setattr(agent, "run_agent", fake_run)
    result = await wait_job(mcp_http, body(await rpc(mcp_http, "agent_start", {
        "brief": "Make two variants", "deliverables": {"count": 2},
        "request_key": "delegate-partial-failure",
    })))
    assert result["state"] == "failed", result
    assert result["result"]["code"] == "execution_failed"
    assert [item["media_ref"] for item in result["result"]["outputs"]] == [uploaded["media_ref"]]
    assert result["result"]["shortfalls"] == ["Requested 2 outputs; the agent marked 1 final."]


async def test_request_key_errors_follow_selected_action_and_hide_large_enums(mcp_http):
    from mcp_server.server import schema_problem
    import jsonschema
    missing = body(await rpc(mcp_http, 'projects_update', {'action': 'create', 'name': 'Sweep'}))
    assert missing['code'] == 'invalid_arguments'
    assert 'request_key' in missing['message'] and 'Generate' in missing['message']
    assert 'const "update"' not in missing['message']
    missing_content = body(await rpc(mcp_http, 'content_update', {'format': 'markdown', 'text': 'hello'}))
    assert 'request_key' in missing_content['message']
    try:
        jsonschema.validate('bad', {'enum': [f'model-{i}' for i in range(10000)]})
    except jsonschema.ValidationError as exc:
        message = schema_problem(exc)
    assert len(message) < 200 and 'tools_options' in message


async def test_creative_containers_roundtrip_and_revision_guards(mcp_http):
    image = await product_upload(mcp_http, product_image_bytes('blue'), 'cell.png')
    async def save(**args):
        return await wait_job(mcp_http, body(await rpc(mcp_http, 'content_update',
            {'request_key': uuid.uuid4().hex, **args})))
    for kind, extras in [('set', {}), ('grid', {'row_headers': ['A', 'B'], 'col_headers': ['1', '2']})]:
        created = await save(format=kind, members=[image['asset_ref']] * 4, title='Comparison', **extras)
        assert created['state'] == 'succeeded', created
        refs = created['result']
        content = body(await rpc(mcp_http, 'content_get', {'ref': refs['asset_ref']}))
        assert len(content['members']) == 4, content
        assert all(member['ref'] == image['asset_ref'] for member in content['members'])
        revised = await save(format=kind, members=[image['asset_ref']] * 4, title='Revised',
                             target_asset_ref=refs['asset_ref'], expected_current_revision=refs['revision_ref'], **extras)
        assert revised['state'] == 'succeeded', revised
        assert revised['result']['asset_ref'] == refs['asset_ref']
        stale = await save(format=kind, members=[image['asset_ref']] * 4, title='Stale',
                           target_asset_ref=refs['asset_ref'], expected_current_revision=refs['revision_ref'], **extras)
        assert stale['result']['code'] == 'revision_conflict', stale
        versions = body(await rpc(mcp_http, 'content_get', {'action': 'revisions', 'ref': refs['asset_ref']}))
        assert len(versions['revisions']) == 2
    invalid = await save(format='grid', members=[image['asset_ref']], title='Wrong size',
                         row_headers=['a', 'b'], col_headers=['1'])
    assert invalid['state'] == 'failed' and 'Expected 2' in invalid['result']['message'], invalid
    package = await save(format='package', title='Deliverable', members=[{'id': 'art', 'ref': image['asset_ref']}],
                         cover='<html><body><h1>Deliverable</h1><stimma-media ref="art"></stimma-media></body></html>',
                         files=[{'name': 'README.md', 'text': 'A deliverable'}])
    assert package['state'] == 'succeeded', package
    package_content = body(await rpc(mcp_http, 'content_get', {'ref': package['result']['asset_ref']}))
    assert package_content['manifest']['title'] == 'Deliverable', package_content
    assert len(package_content['manifest']['members']) == 1
    edited = await save(format='package', source_ref=package['result']['media_ref'],
                        target_asset_ref=package['result']['asset_ref'], expected_current_revision=package['result']['revision_ref'],
                        cover='<html><body><h1>Revised cover</h1></body></html>')
    assert edited['state'] == 'succeeded', edited
    exported = await save(format='export', source_ref=edited['result']['media_ref'], output_format='html')
    assert exported['state'] == 'succeeded', exported
    url = body(await rpc(mcp_http, 'media_export', {'ref': exported['result']['media_ref']}))['download_url']
    assert b'Revised cover' in (await mcp_http.get(url)).content
    recipes = body(await rpc(mcp_http, 'content_get', {'action': 'recipes'}))
    assert recipes['recipes']
    layout = await save(format='layout', files=[{'name': 'index.html', 'text': '<html><body><img src="art.png"></body></html>'},
                                              {'name': 'art.png', 'source_ref': image['media_ref']}])
    assert layout['state'] == 'succeeded', layout
    content = body(await rpc(mcp_http, 'content_get', {'ref': layout['result']['asset_ref']}))
    assert {f['name'] for f in content['files']} >= {'index.html', 'art.png'}
    invalid = await save(format='layout', files=[{'name': '../escape.html', 'text': 'no'}])
    assert invalid['state'] == 'failed' and invalid['result']['code'] == 'invalid_arguments'


async def test_batch_progress_failure_retry_and_restart_preserve_outputs(mcp_http, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from mcp_server import jobs, workspace
    from mcp_server.access import access
    from mcp_server.models import McpOperation
    from database_registry import get_database_registry
    from agent.v2.code_runtime import StimmaSDK, ToolResult
    from PIL import Image
    from agent.v2.tools.call_tool import ToolExecutionFailed
    descriptor = SimpleNamespace(parameter_schema={'type': 'object', 'properties': {'index': {'type': 'integer'}}}, output_schema={}, metadata={})
    async def descriptor_for(*args):
        return 'test:sweep', None, descriptor
    monkeypatch.setattr(workspace, 'tool_descriptor', descriptor_for)
    reached, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def dispatch(self, tool_id, **kwargs):
        index = kwargs['_params_dict']['index']
        calls.append(index)
        if index == 1 and len(calls) == 2:
            reached.set()
            await release.wait()
        if index == 5 and calls.count(5) == 1:
            raise ToolExecutionFailed('Missing model krea2/checkpoints/model.safetensors')
        path = tmp_path / f'cell-{index}.png'
        Image.new('RGB', (8, 8), (index * 2, 100, 200)).save(path)
        return ToolResult(path=path, tool_name=tool_id, parameters=kwargs['_params_dict'])
    monkeypatch.setattr(StimmaSDK, '_dispatch_tool', dispatch)
    caller = await access.authenticate('default', 'test-credential-one')
    accepted = body(await rpc(mcp_http, 'tools_run', {'tool_ref': access.ref(caller, 'tool', 'test:sweep'),
        'schema_version': workspace.tool_version(descriptor), 'batch': [{'index': i} for i in range(100)],
        'batch_labels': [f'cell-{i}' for i in range(100)], 'title': 'Ten by ten sweep', 'request_key': 'parity-sweep'}))
    try:
        await asyncio.wait_for(reached.wait(), 10)
        running = body(await rpc(mcp_http, 'jobs_get', {'job_ref': accepted['job_ref']}))
        assert running['progress'] == {'total': 100, 'completed': 1, 'failed': 0, 'interrupted': 0, 'remaining': 99, 'active_index': 1}, running
        assert len(running['result']['items']) == 1
    finally:
        release.set()
    done = await wait_job(mcp_http, accepted)
    assert done['progress']['completed'] == 99 and done['progress']['failed'] == 1, done
    assert 'krea2/checkpoints/model.safetensors' in done['result']['items'][5]['error']['message']
    retried = await wait_job(mcp_http, body(await rpc(mcp_http, 'jobs_retry', {'job_ref': done['job_ref'], 'request_key': 'parity-retry'})))
    assert retried['state'] == 'succeeded' and retried['result']['items'][0]['original_index'] == 5, retried
    assert len(calls) == 101
    completed = {item['original_index']: item['output']['asset_ref'] for item in done['result']['items'] if item['state'] == 'succeeded'}
    completed[5] = retried['result']['items'][0]['output']['asset_ref']
    grid = await wait_job(mcp_http, body(await rpc(mcp_http, 'content_update', {
        'format': 'grid', 'title': 'Ten prompts by ten models', 'members': [completed[i] for i in range(100)],
        'row_headers': [f'Prompt {i}' for i in range(10)], 'col_headers': [f'Model {i}' for i in range(10)],
        'request_key': 'hundred-image-grid'})))
    assert grid['state'] == 'succeeded', grid
    grid_content = body(await rpc(mcp_http, 'content_get', {'ref': grid['result']['asset_ref']}))
    assert len(grid_content['members']) == 100
    assert grid_content['members'][55]['row'] == 5 and grid_content['members'][55]['col'] == 5
    # Simulate a persisted running operation after a process restart: no caller/task survives.
    db = get_database_registry().get_database(caller.profile_id)
    async with db.async_session_maker() as session:
        job = await session.get(McpOperation, access.resolve(caller, done['job_ref'], 'job'))
        job.state = 'running'
        await session.commit()
    recovered = body(await rpc(mcp_http, 'jobs_get', {'job_ref': done['job_ref']}))
    assert recovered['state'] == 'interrupted'
    assert recovered['result']['items'] == done['result']['items']
    assert recovered['progress']['completed'] == 99


async def test_document_restore_layout_edit_and_sprite_exports(mcp_http):
    async def save(**args):
        accepted = body(await rpc(mcp_http, 'content_update', {'request_key': uuid.uuid4().hex, **args}))
        assert 'job_ref' in accepted, accepted
        done = await wait_job(mcp_http, accepted)
        assert done['state'] == 'succeeded', done
        return done['result']
    image = await product_upload(mcp_http, product_image_bytes('red'), 'sprite.png')
    layout = await save(format='layout', files=[{'name': 'index.html', 'text': '<html><body>First</body></html>'},
                                              {'name': 'art.png', 'source_ref': image['media_ref']}])
    revised = await save(format='layout', source_ref=layout['media_ref'], target_asset_ref=layout['asset_ref'],
                         expected_current_revision=layout['revision_ref'], files=[{'name': 'index.html', 'text': '<html><body>Second</body></html>'}])
    inspected = body(await rpc(mcp_http, 'content_get', {'ref': revised['asset_ref']}))
    assert any(f['name'] == 'art.png' for f in inspected['files'])
    restored = await save(format='restore', target_asset_ref=layout['asset_ref'], expected_current_revision=revised['revision_ref'],
                          revision_ref=layout['revision_ref'])
    assert restored['revision_ref'] not in (layout['revision_ref'], revised['revision_ref'])
    inspected = body(await rpc(mcp_http, 'content_get', {'ref': restored['asset_ref']}))
    assert 'First' in next(f['text'] for f in inspected['files'] if f['name'] == 'index.html')
    sprite = await save(format='sprite', document={'type': 'sprite', 'version': 1, 'title': 'Character',
        'anchor': {'x': 0.5, 'y': 1}, 'base_image': {'ref': image['media_ref']}, 'animations': [{
            'name': 'idle', 'loop': 'loop', 'loop_start': 0, 'loop_end': 0, 'fps': 12,
            'animation': {'ref': image['media_ref']}, 'frame_count': 1,
            'frames': [{'duration_ms': 100, 'rects': {}, 'events': []}]}]})
    inspected = body(await rpc(mcp_http, 'content_get', {'ref': sprite['asset_ref']}))
    assert inspected['document']['base_image']['ref'] == image['media_ref']
    output = await save(format='export', source_ref=sprite['media_ref'], output_format='godot')
    download = await mcp_http.get(output['download_url'])
    assert download.status_code == 200 and download.content.startswith(b'PK')


async def test_tool_inspection_compacts_options_and_refreshes_catalog(mcp_http, monkeypatch):
    from types import SimpleNamespace
    from providers.registry import ProviderRegistry
    from mcp_server import workspace
    from mcp_server.access import access
    tool = SimpleNamespace(name='Generator', description='Test', parameter_schema={'type': 'object',
        'properties': {'model': {'type': 'string', 'enum': [f'model-{i}' for i in range(1000)]}, 'prompt': {'type': 'string'}},
        'required': ['model', 'prompt']}, output_schema={}, metadata={})
    provider = SimpleNamespace(provider_id='test', status=SimpleNamespace(value='connected'))
    async def descriptor(*args):
        return 'test:generator', provider, tool
    async def refresh(self, provider_id, force_refresh):
        assert provider_id == 'test' and force_refresh
        tool.parameter_schema['properties']['model']['enum'].append('new-model')
    monkeypatch.setattr(workspace, 'tool_descriptor', descriptor)
    monkeypatch.setattr(ProviderRegistry, 'refresh_tools', refresh)
    caller = await access.authenticate('default', 'test-credential-one')
    ref = access.ref(caller, 'tool', 'test:generator')
    before = body(await rpc(mcp_http, 'tools_inspect', {'tool_ref': ref, 'fields': ['model']}))
    assert set(before['parameter_schema']['properties']) == {'model'}
    assert before['parameter_schema']['properties']['model']['x-enum-count'] == 1000
    after = body(await rpc(mcp_http, 'tools_inspect', {'tool_ref': ref, 'refresh': True, 'include_options': True}))
    assert after['schema_version'] != before['schema_version']
    assert len(after['parameter_schema']['properties']['model']['enum']) == 1001


async def test_package_recipe_roundtrip(mcp_http):
    palette = await product_upload(mcp_http, json.dumps({'colors': [{'name': 'ink', 'hex': '#223344'}]}).encode(), 'palette.json', staged=True)
    accepted = body(await rpc(mcp_http, 'content_update', {'format': 'package', 'title': 'Palette',
        'members': [{'id': 'colors', 'ref': palette['media_ref'], 'role': 'palette'}],
        'runs': [{'recipe': 'palette-exports', 'inputs': {'palette': 'colors'}}],
        'cover': '<html><body><h1>Palette</h1><stimma-files></stimma-files></body></html>', 'request_key': 'palette-recipe'}))
    done = await wait_job(mcp_http, accepted)
    assert done['state'] == 'succeeded', done
    content = body(await rpc(mcp_http, 'content_get', {'ref': done['result']['asset_ref']}))
    assert len(content['manifest']['runs']) == 1
    run = content['manifest']['runs'][0]
    assert run['recipe']['id'] == 'palette-exports'
    assert len(run['files']) == 3
    revised = await wait_job(mcp_http, body(await rpc(mcp_http, 'content_update', {'format': 'package',
        'source_ref': done['result']['media_ref'], 'target_asset_ref': done['result']['asset_ref'],
        'expected_current_revision': done['result']['revision_ref'], 'runs': [{'rerun': run['id']}],
        'request_key': 'palette-rerun'})))
    assert revised['state'] == 'succeeded', revised
