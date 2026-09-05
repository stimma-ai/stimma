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
