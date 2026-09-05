"""Headless lifecycle and container-local control. Desktop imports remain inert."""
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

ENABLED = os.environ.get('STIMMA_HEADLESS') == '1'
ROOT = Path(os.environ.get('STIMMA_HEADLESS_ROOT', '/data'))
router = APIRouter(prefix='/api/headless', tags=['headless'])
_maintenance = False
_active_requests = 0
_login_task = None
_paused_flow_runs = set()


def is_in_maintenance():
    return ENABLED and _maintenance


async def drain_flows(enabled):
    from flow_registry import all_runtimes
    if not enabled:
        for run in list(_paused_flow_runs):
            await run.resume()
            _paused_flow_runs.discard(run)
        return 0
    busy = 0
    for runtime in all_runtimes():
        run = runtime.run
        if run is None:
            continue
        if run.state == 'running':
            await run.pause()
            _paused_flow_runs.add(run)
        busy += run.active_evaluation_count
    return busy


def supervisor_command(action):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(ROOT / 'control.sock'))
        client.sendall((json.dumps({'action': action}) + '\n').encode())
        with client.makefile('r') as stream:
            result = json.loads(stream.readline(1024 * 1024))
    if result.get('error') and not result.get('headless'):
        raise HTTPException(409, result['error'])
    return result


def require_internal(request):
    expected = os.environ.get('STIMMA_SUPERVISOR_TOKEN', '')
    if not ENABLED or not expected or not secrets.compare_digest(request.headers.get('X-Stimma-Supervisor', ''), expected):
        raise HTTPException(403, 'Container-local operation')


@router.get('/status')
async def status():
    if not ENABLED:
        return {'headless': False}
    try:
        return await asyncio.to_thread(supervisor_command, 'status')
    except OSError:
        raise HTTPException(503, 'Server supervisor is unavailable')


@router.post('/check')
@router.post('/update')
@router.post('/restart')
@router.post('/login')
@router.post('/logout')
async def command(request: Request):
    action = request.url.path.rsplit('/', 1)[-1]
    if action in ('login', 'logout'):
        require_internal(request)
        if action == 'login':
            start_login()
        else:
            global _login_task
            if _login_task:
                _login_task.cancel()
            from routes.auth import logout
            await logout()
        return {'accepted': True}
    if action not in ('check', 'update', 'restart'):
        raise HTTPException(404, 'Unknown server command')
    if not ENABLED:
        raise HTTPException(409, 'This server is managed by the desktop app')
    from privacy_lockdown import is_privacy_lockdown_enabled
    if action != 'restart' and is_privacy_lockdown_enabled():
        raise HTTPException(403, 'Updates are paused by Privacy Lockdown')
    return await asyncio.to_thread(supervisor_command, action)


@router.get('/ready')
async def ready(request: Request):
    require_internal(request)
    return {'ready': True}


class MaintenanceRequest(BaseModel):
    enabled: bool


@router.post('/maintenance')
async def maintenance(request: Request, body: MaintenanceRequest):
    require_internal(request)
    global _maintenance
    _maintenance = body.enabled
    marker = ROOT / 'maintenance'
    if body.enabled:
        marker.touch(mode=0o600)
    else:
        marker.unlink(missing_ok=True)
    from agent.v2.service import get_active_chat_ids
    from config import get_settings
    from database import GenerationJob, DeleteOperation
    from database_registry import get_database_registry
    from sqlalchemy import func, select
    busy = len(get_active_chat_ids()) + _active_requests + await drain_flows(body.enabled)
    registry = get_database_registry()
    for profile in get_settings().profiles:
        db = registry.get_database(profile.id)
        async with db.async_session_maker() as session:
            for model, condition in (
                (GenerationJob, GenerationJob.status.in_(['queued', 'assigned', 'processing'])),
                (DeleteOperation, DeleteOperation.status.in_(['queued', 'running'])),
            ):
                busy += await session.scalar(select(func.count()).select_from(model).where(condition)) or 0
    # The ingestion process acknowledges only between complete processing batches.
    ingestion_idle = (ROOT / 'ingestion-idle').exists()
    return {'idle': busy == 0 and ingestion_idle, 'activeWork': busy, 'ingestionIdle': ingestion_idle}


class MaintenanceGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        global _active_requests
        if scope['type'] != 'http' or scope.get('path', '').startswith('/api/headless/'):
            return await self.app(scope, receive, send)
        if _maintenance and scope['method'] not in ('GET', 'HEAD', 'OPTIONS'):
            from starlette.responses import JSONResponse
            return await JSONResponse({'detail': 'Server is waiting to restart; try again shortly'}, status_code=503)(scope, receive, send)
        _active_requests += 1
        try:
            await self.app(scope, receive, send)
        finally:
            _active_requests -= 1


async def finish_login(custom_token, user):
    """Shared Firebase completion for desktop callback and device authorization."""
    from firebase_auth import exchange_custom_token
    from auth_storage import save_auth_state
    from cloud_api import fetch_user_account
    from routes.cloud import connect_cloud_internal
    tokens = await exchange_custom_token(custom_token)
    account = await fetch_user_account(tokens['id_token'])
    credits = account.get('credits', 0)
    save_auth_state({
        'user': user, 'credits': credits,
        'ever_had_credits': bool(account.get('hasEverHadCredits', credits > 0)),
        'refresh_token': tokens['refresh_token'], 'id_token': tokens['id_token'],
        'id_token_expiry': tokens['expiry'],
    })
    asyncio.create_task(connect_cloud_internal(tokens['id_token']))
    from cloud_events import get_cloud_events_client
    get_cloud_events_client().start()
    return credits


async def device_login():
    import httpx
    from config import get_settings
    from cloud_runtime import with_cloud_access_headers
    from privacy_lockdown import is_privacy_lockdown_enabled
    if is_privacy_lockdown_enabled():
        return
    base = get_settings().cloud.base_url.rstrip('/')
    async with httpx.AsyncClient(headers=with_cloud_access_headers(), timeout=30) as client:
        response = await client.post(f'{base}/api/auth/device/start', json={'name': os.environ.get('STIMMA_SERVER_NAME', 'Stimma Server')})
        response.raise_for_status()
        attempt = response.json()
        print(f"\n[stimma] Sign in: {attempt['verification_url']}\n[stimma] Code: {attempt['user_code']}\n", flush=True)
        deadline = asyncio.get_running_loop().time() + attempt['expires_in']
        interval = attempt['interval']
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(interval)
            if is_privacy_lockdown_enabled():
                return
            try:
                response = await client.post(f'{base}/api/auth/device/poll', json={'device_code': attempt['device_code']})
                if response.status_code >= 500:
                    interval = min(interval + 5, 30)
                    continue
                data = response.json()
            except httpx.TransportError:
                interval = min(interval + 5, 30)
                continue
            if data.get('error') in ('authorization_pending', 'slow_down'):
                if data['error'] == 'slow_down':
                    interval = min(interval + 5, 30)
                continue
            response.raise_for_status()
            await finish_login(data['custom_token'], data['user'])
            from multi_device.service import apply_serving
            await apply_serving(True)
            print('[stimma] Signed in. Server ready.', flush=True)
            return
        print('[stimma] Login code expired. Run: docker exec stimma stimma-server login', flush=True)


def start_login():
    global _login_task
    if _login_task and not _login_task.done():
        _login_task.cancel()
    _login_task = asyncio.create_task(device_login())
    def done(task):
        if not task.cancelled() and task.exception():
            print('[stimma] Login failed. Run: docker exec stimma stimma-server login', flush=True)
    _login_task.add_done_callback(done)


async def startup():
    for name in ('maintenance', 'ingestion-idle'):
        (ROOT / name).unlink(missing_ok=True)
    from auth_storage import load_auth_state
    from multi_device.service import apply_serving
    from privacy_lockdown import is_privacy_lockdown_enabled
    if is_privacy_lockdown_enabled():
        return
    if not os.environ.get('STIMMA_ADVERTISE_HOST'):
        print('[stimma] Set STIMMA_ADVERTISE_HOST to the server LAN IP or tailnet hostname for Docker bridge networking.', flush=True)
    state = load_auth_state()
    if state and state.get('refresh_token'):
        await apply_serving(True)
    else:
        start_login()
