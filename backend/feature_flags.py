"""
PostHog feature flag client for the sidecar.

Polls PostHog's public ``/decide`` endpoint every 30 seconds with the
project public key. ``/decide`` returns flag values pre-evaluated for the
distinct_id, so we don't need a personal/secure API key (which would be
unsafe to ship in the desktop binary).

Reads (``is_enabled`` / ``get``) are synchronous dict lookups — cheap from
any code path. The on-disk cache (``flags.json`` in the app data dir)
lets us seed correct values before the first poll completes, including
on a cold start with no network.
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

import app_dirs
from core.logging import get_logger
from feature_flag_defaults import FLAG_DEFAULTS

log = get_logger(__name__)

POSTHOG_HOST = "https://us.i.posthog.com"
POSTHOG_PROJECT_KEY = "phc_qyrQKHfPzCsSvBuY5tywS2TXZyvF8Q6cZU8tmGSNpxbp"
POLL_INTERVAL_SECONDS = 30
DECIDE_TIMEOUT_SECONDS = 10


def _cache_path() -> Path:
    return app_dirs.get_data_dir() / "flags.json"


def _load_cache() -> Dict[str, Any]:
    try:
        path = _cache_path()
        if path.exists():
            with open(path) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
    except Exception as e:
        log.info(f"feature_flags: failed to load cache: {e}")
    return {}


def _save_cache(flags: Dict[str, Any]) -> None:
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(flags, f)
        os.replace(tmp, path)
    except Exception as e:
        log.info(f"feature_flags: failed to save cache: {e}")


class FeatureFlagClient:
    def __init__(self) -> None:
        self._flags: Dict[str, Any] = {}
        self._poll_task: Optional[asyncio.Task] = None
        self._subscribers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._started: bool = False

    def is_enabled(self, name: str, default: bool = False) -> bool:
        """Return whether a boolean flag is enabled."""
        value = self._flags.get(name, FLAG_DEFAULTS.get(name, default))
        return bool(value) and value is not False

    def get(self, name: str, default: Any = None) -> Any:
        """Return a flag value (multivariate flags return strings; boolean flags return bool)."""
        if name in self._flags:
            return self._flags[name]
        if name in FLAG_DEFAULTS:
            return FLAG_DEFAULTS[name]
        return default

    def all(self) -> Dict[str, Any]:
        """Return a snapshot of the current flag dict (for diagnostics / WS push)."""
        return dict(self._flags)

    def subscribe(
        self, callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> Callable[[], None]:
        """Register an async callback fired with the new flags dict on each change.

        Returns a function that unsubscribes when called.
        """
        self._subscribers.append(callback)

        def _unsub() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsub

    async def start(self) -> None:
        """Hydrate from disk cache and kick off the poll loop."""
        if self._started:
            return
        self._started = True
        self._flags = _load_cache()
        self._poll_task = asyncio.create_task(self._poll_loop())
        log.info("feature_flags started", cached_count=len(self._flags))

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        self._started = False

    def _distinct_id(self) -> Optional[str]:
        """Match the telemetry client's identification rule."""
        try:
            from telemetry import get_telemetry_client
            tc = get_telemetry_client()
            return tc._distinct_id()
        except Exception:
            return None

    async def _poll_loop(self) -> None:
        # Initial fetch on a slight delay so install_id has a chance to settle.
        await asyncio.sleep(0.5)
        while True:
            try:
                await self._fetch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("feature_flags: poll iteration failed")
            try:
                await asyncio.sleep(POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise

    async def _fetch_once(self) -> None:
        distinct_id = self._distinct_id()
        if not distinct_id:
            return  # no identity yet; try again next tick

        payload = {
            "api_key": POSTHOG_PROJECT_KEY,
            "distinct_id": distinct_id,
        }
        url = f"{POSTHOG_HOST}/decide/?v=3"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(DECIDE_TIMEOUT_SECONDS)) as client:
                response = await client.post(url, json=payload)
            if response.status_code != 200:
                log.debug(
                    f"feature_flags: /decide returned status {response.status_code}"
                )
                return
            body = response.json()
        except Exception as e:
            log.debug(f"feature_flags: /decide request failed: {e}")
            return

        new_flags = body.get("featureFlags") or {}
        if not isinstance(new_flags, dict):
            return

        if new_flags == self._flags:
            return

        self._flags = new_flags
        _save_cache(new_flags)
        log.info("feature_flags updated", count=len(new_flags))
        snapshot = dict(new_flags)
        for cb in list(self._subscribers):
            asyncio.create_task(self._safe_call(cb, snapshot))

    async def _safe_call(
        self,
        cb: Callable[[Dict[str, Any]], Awaitable[None]],
        snapshot: Dict[str, Any],
    ) -> None:
        try:
            await cb(snapshot)
        except Exception:
            log.exception("feature_flags: subscriber callback failed")


_client: Optional[FeatureFlagClient] = None


def get_feature_flags() -> FeatureFlagClient:
    global _client
    if _client is None:
        _client = FeatureFlagClient()
    return _client


def is_enabled(name: str, default: bool = False) -> bool:
    return get_feature_flags().is_enabled(name, default)


def get(name: str, default: Any = None) -> Any:
    return get_feature_flags().get(name, default)
