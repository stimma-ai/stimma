"""
First-party feature flag client for the sidecar.

Fetches ``GET {cloud.base_url}/api/feature-flags`` on launch, then every
6 hours, plus on sign-in change. Identity/platform ride the User-Agent
(user_agent.py); a Firebase bearer token is attached when signed in so
flags can later target users/tiers. The server returns ``{}`` today — the
client system is fully functional with an empty bag.

This fetch runs in ALL distributions (dev and official) — it is an
operational config fetch and the install/MAU signal for source builds.
It carries no usage data and is not gated by telemetry consent. It IS
suppressed by ``DO_NOT_TRACK=1`` (D11: no automatic requests at all —
local defaults only).

Reads (``get_bool`` / ``get`` / ``has``) are synchronous dict lookups —
cheap from any code path. The on-disk cache (``flags.json`` in the app
data dir) seeds values before the first fetch completes, including on a
cold start with no network. ``feature_flag_defaults.py`` provides local
fallbacks for flags the server hasn't defined.
"""
import asyncio
import json
import os
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx

import app_dirs
from core.logging import get_logger
from distribution import is_dnt
from feature_flag_defaults import FLAG_DEFAULTS

log = get_logger(__name__)

FETCH_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours
FETCH_TIMEOUT_SECONDS = 15


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
        self._refresh_event: Optional[asyncio.Event] = None
        self._subscribers: List[Callable[[Dict[str, Any]], Awaitable[None]]] = []
        self._started: bool = False

    # ── Read API ────────────────────────────────────────────────────────

    def get_bool(self, name: str, default: bool = False) -> bool:
        """Return whether a boolean flag is enabled."""
        value = self._flags.get(name, FLAG_DEFAULTS.get(name, default))
        return bool(value) and value is not False

    # Back-compat alias for existing call sites.
    def is_enabled(self, name: str, default: bool = False) -> bool:
        return self.get_bool(name, default)

    def get(self, name: str, default: Any = None) -> Any:
        """Return a flag value (arbitrary JSON value)."""
        if name in self._flags:
            return self._flags[name]
        if name in FLAG_DEFAULTS:
            return FLAG_DEFAULTS[name]
        return default

    def has(self, name: str) -> bool:
        """Whether the flag is defined (server bag or local defaults)."""
        return name in self._flags or name in FLAG_DEFAULTS

    def all(self) -> Dict[str, Any]:
        """Snapshot of the effective flag dict (defaults overlaid by server)."""
        merged = dict(FLAG_DEFAULTS)
        merged.update(self._flags)
        return merged

    def subscribe(
        self, callback: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> Callable[[], None]:
        """Register an async callback fired with the new flags dict on change.

        Returns a function that unsubscribes when called.
        """
        self._subscribers.append(callback)

        def _unsub() -> None:
            try:
                self._subscribers.remove(callback)
            except ValueError:
                pass

        return _unsub

    # ── Lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Hydrate from disk cache and kick off the fetch loop."""
        if self._started:
            return
        self._started = True
        self._flags = _load_cache()
        if is_dnt():
            log.info(
                "feature_flags: DO_NOT_TRACK=1 — no fetch, local defaults only",
                cached_count=len(self._flags),
            )
            return
        self._refresh_event = asyncio.Event()
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

    def refresh(self) -> None:
        """Request an immediate re-fetch (e.g. on sign-in change)."""
        if self._refresh_event is not None:
            self._refresh_event.set()

    # ── Fetching ────────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        # Initial fetch shortly after startup.
        await asyncio.sleep(0.5)
        while True:
            try:
                await self._fetch_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("feature_flags: fetch iteration failed")
            # Sleep until the next interval or an explicit refresh request.
            try:
                self._refresh_event.clear()
                await asyncio.wait_for(
                    self._refresh_event.wait(), timeout=FETCH_INTERVAL_SECONDS
                )
            except asyncio.TimeoutError:
                pass
            except asyncio.CancelledError:
                raise

    async def _bearer_token(self) -> Optional[str]:
        try:
            from firebase_auth import get_valid_id_token
            return await get_valid_id_token()
        except Exception:
            return None

    async def _fetch_once(self) -> None:
        if is_dnt():
            return
        from config import get_settings
        from user_agent import ua_headers

        base_url = get_settings().cloud.base_url.rstrip("/")
        url = f"{base_url}/api/feature-flags"
        headers = ua_headers()
        token = await self._bearer_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS)
            ) as client:
                response = await client.get(url, headers=headers)
            if response.status_code != 200:
                log.debug(
                    f"feature_flags: fetch returned status {response.status_code}"
                )
                return
            body = response.json()
        except Exception as e:
            log.debug(f"feature_flags: fetch failed: {e}")
            return

        new_flags = body if isinstance(body, dict) else {}
        # Tolerate a wrapped shape ({"flags": {...}}) as well as the bare bag.
        if isinstance(new_flags.get("flags"), dict) and len(new_flags) == 1:
            new_flags = new_flags["flags"]

        if new_flags == self._flags:
            return

        self._flags = new_flags
        _save_cache(new_flags)
        log.info("feature_flags updated", count=len(new_flags))
        snapshot = self.all()
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


def get_bool(name: str, default: bool = False) -> bool:
    return get_feature_flags().get_bool(name, default)


def is_enabled(name: str, default: bool = False) -> bool:
    return get_feature_flags().get_bool(name, default)


def get(name: str, default: Any = None) -> Any:
    return get_feature_flags().get(name, default)


def has(name: str) -> bool:
    return get_feature_flags().has(name)
