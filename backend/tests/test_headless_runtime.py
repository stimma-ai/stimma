from unittest.mock import Mock
import httpx
import pytest
from fastapi import FastAPI
import headless_runtime as runtime


@pytest.fixture
def app():
    app = FastAPI()
    app.include_router(runtime.router)
    return app


@pytest.mark.asyncio
async def test_desktop_capability_and_unsupported_commands(app, monkeypatch):
    monkeypatch.setattr(runtime, 'ENABLED', False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.get('/api/headless/status')).json() == {'headless': False}
        assert (await client.post('/api/headless/restart')).status_code == 409
        assert (await client.post('/api/headless/arbitrary')).status_code == 404


@pytest.mark.asyncio
async def test_management_targets_supervisor_but_internal_routes_require_secret(app, monkeypatch):
    monkeypatch.setattr(runtime, 'ENABLED', True)
    monkeypatch.setenv('STIMMA_SUPERVISOR_TOKEN', 'private')
    command = Mock(return_value={'headless': True, 'status': 'ready'})
    monkeypatch.setattr(runtime, 'supervisor_command', command)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.post('/api/headless/restart')).status_code == 200
        command.assert_called_once_with('restart')
        assert (await client.get('/api/headless/ready')).status_code == 403
        assert (await client.post('/api/headless/login')).status_code == 403
        assert (await client.post('/api/headless/maintenance', json={'enabled': True})).status_code == 403
        assert (await client.get('/api/headless/ready', headers={'X-Stimma-Supervisor': 'private'})).status_code == 200


@pytest.mark.asyncio
async def test_maintenance_blocks_new_writes_and_allows_status(monkeypatch):
    app = FastAPI()
    @app.post('/work')
    async def work():
        return {'started': True}
    @app.get('/status')
    async def status():
        return {'ok': True}
    app.add_middleware(runtime.MaintenanceGate)
    monkeypatch.setattr(runtime, '_maintenance', True)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        assert (await client.post('/work')).status_code == 503
        assert (await client.get('/status')).status_code == 200
    assert runtime._active_requests == 0


@pytest.mark.asyncio
async def test_flow_drain_waits_for_evaluations_not_running_labels(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    import flow_registry

    def flow(state, active):
        run = Mock(state=state, active_evaluation_count=active)
        async def pause():
            run.state = 'paused'
        async def resume():
            run.state = 'running'
        run.pause = AsyncMock(side_effect=pause)
        run.resume = AsyncMock(side_effect=resume)
        return SimpleNamespace(run=run)

    waiting = flow('running', 0)
    working = flow('running', 1)
    user_paused = flow('paused', 0)
    monkeypatch.setattr(flow_registry, 'all_runtimes', lambda: [waiting, working, user_paused])
    monkeypatch.setattr(runtime, '_paused_flow_runs', set())
    assert await runtime.drain_flows(True) == 1
    working.run.active_evaluation_count = 0
    assert await runtime.drain_flows(True) == 0
    assert waiting.run.state == 'paused'
    assert working.run.state == 'paused'
    await runtime.drain_flows(False)
    assert waiting.run.state == working.run.state == 'running'
    user_paused.run.resume.assert_not_called()


@pytest.mark.asyncio
async def test_read_side_flow_recovery_cannot_restart_during_maintenance(monkeypatch):
    from flow_runtime.runtime import FlowRuntime
    monkeypatch.setattr(runtime, 'ENABLED', True)
    monkeypatch.setattr(runtime, '_maintenance', True)
    flow = Mock()
    await FlowRuntime.start(flow)
    flow.build_initial_graph.assert_not_called()
