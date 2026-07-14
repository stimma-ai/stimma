"""
Account-events client: persistent WebSocket to Stimma Cloud.

Connects to {cloud_base_url}/account-events-v1 whenever the user is signed in
and listens for account-change nudges (balance, entitlements). Events carry no data; on each one the client re-fetches account
state and applies it via account_sync (persist, tool connect/disconnect,
frontend broadcast). An initial refresh runs on every (re)connect, which also
catches anything that changed while the channel was down or the app closed.

Fully separate from the STP tool provider channel.
"""
import asyncio
import contextlib
import json
import random

import aiohttp

from config import get_settings
from core.logging import get_logger
from cloud_runtime import cloud_access_headers
from privacy_lockdown import is_privacy_lockdown_enabled

log = get_logger(__name__)

PING_INTERVAL_S = 30
RECONNECT_MIN_S = 2
RECONNECT_MAX_S = 60
# Coalesce bursts (e.g. webhook fan-out) into one account refresh.
EVENT_DEBOUNCE_S = 0.5


def _http_to_ws_url(http_url: str) -> str:
    if http_url.startswith("https://"):
        return "wss://" + http_url[8:]
    if http_url.startswith("http://"):
        return "ws://" + http_url[7:]
    return http_url


class CloudEventsClient:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._refresh_task: asyncio.Task | None = None

    def start(self) -> None:
        """Start (or keep) the connection loop. Idempotent; no-op when signed
        out or in Privacy Lockdown."""
        if is_privacy_lockdown_enabled():
            return
        from auth_storage import load_auth_state

        auth_state = load_auth_state()
        if not auth_state or not auth_state.get('refresh_token'):
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="cloud-account-events")

    async def stop(self) -> None:
        for task in (self._task, self._refresh_task):
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._task = None
        self._refresh_task = None

    def _schedule_refresh(self, reason: str) -> None:
        """Debounced account refresh — one fetch per burst of events."""
        if self._refresh_task and not self._refresh_task.done():
            return

        async def _refresh() -> None:
            await asyncio.sleep(EVENT_DEBOUNCE_S)
            from account_sync import refresh_account_state
            await refresh_account_state(f"account_event:{reason}")

        self._refresh_task = asyncio.create_task(_refresh())

    async def _run(self) -> None:
        from auth_storage import load_auth_state
        from firebase_auth import get_valid_id_token

        backoff = RECONNECT_MIN_S
        while True:
            auth_state = load_auth_state()
            if not auth_state or not auth_state.get('refresh_token'):
                log.info("account-events: signed out, stopping")
                return
            if is_privacy_lockdown_enabled():
                log.info("account-events: privacy lockdown, stopping")
                return

            try:
                token = await get_valid_id_token()
            except Exception as e:
                log.warning("account-events: token refresh failed", error=str(e))
                token = None

            if token:
                try:
                    await self._connect_and_listen(token)
                    backoff = RECONNECT_MIN_S  # clean-ish session; reset
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.warning("account-events: connection error", error=str(e))

            delay = backoff + random.uniform(0, backoff / 2)
            backoff = min(backoff * 2, RECONNECT_MAX_S)
            await asyncio.sleep(delay)

    async def _connect_and_listen(self, token: str) -> None:
        base_url = get_settings().cloud.base_url
        ws_url = _http_to_ws_url(base_url) + "/account-events-v1"
        headers = dict(cloud_access_headers())
        headers["Authorization"] = f"Bearer {token}"

        session = aiohttp.ClientSession()
        try:
            async with session.ws_connect(ws_url, headers=headers, heartbeat=None) as ws:
                log.info("account-events: connected")

                # Sync now — covers events missed while disconnected and the
                # app-was-closed-during-purchase case.
                from account_sync import refresh_account_state
                await refresh_account_state("events_connected")

                ping_task = asyncio.create_task(self._ping_loop(ws))
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self._handle_message(msg.data)
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                finally:
                    ping_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await ping_task
                log.info("account-events: disconnected")
        finally:
            await session.close()

    def _handle_message(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return
        if not isinstance(data, dict):
            return
        if data.get('type') == 'account_event':
            reason = data.get('reason') or 'account'
            log.info("account-events: event received", reason=reason)
            self._schedule_refresh(reason)
        # 'pong' and anything else: ignore

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        # App-level ping matched by the DO's hibernation auto-response, so
        # keepalive doesn't wake (and bill) the durable object.
        while True:
            await asyncio.sleep(PING_INTERVAL_S)
            await ws.send_str('{"type":"ping"}')


_client = CloudEventsClient()


def get_cloud_events_client() -> CloudEventsClient:
    return _client
