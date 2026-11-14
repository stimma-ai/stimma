"""Telling the editor a prepared prompt changed, so it looks again instead of polling.

One event, `fluent_prompt_changed` with the prompt's key and its profile: a reading landed (a
prompt settled, slots._settle -> program.on_prepared), a variant of a pool was stored, a pool's
write ended (kept something or failed), or a variant was removed. A pool can serve several
prompts, so the prompts the editor was shown (`watch`, from /prepare and /pools) are remembered
by the pools they draw from. Events for one prompt arriving together go out as one. Never raises
and never blocks the caller; with no event loop to send on, nothing is sent (the editor's slow
poll still finds it).
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Any, Dict, Optional, Set, Tuple

from core.logging import get_logger

log = get_logger(__name__)

EVENT = "fluent_prompt_changed"
WATCHED = 2000      # pools remembered (the oldest go first)
GATHER = 0.25       # seconds events for one prompt are gathered into one

_pools: "OrderedDict[str, Tuple[Optional[str], Set[str]]]" = OrderedDict()   # pool -> (profile, prompt keys)
_loop: Optional[asyncio.AbstractEventLoop] = None
_pending: Dict[Tuple[str, Optional[str]], None] = {}
_flush: Optional[asyncio.TimerHandle] = None


def watch(entry: Dict[str, Any], profile_id: Optional[str]) -> None:
    """The editor was shown this prompt: a change to any pool it draws from is news for it."""
    global _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        pass
    key = entry.get("key")
    if not key:
        return
    for s in entry.get("slots") or []:
        for pool in (s.get("pool"), s.get("stand_in")):
            if not pool:
                continue
            prof, keys = _pools.pop(str(pool), (profile_id, set()))
            keys.add(str(key))
            _pools[str(pool)] = (profile_id or prof, set(list(keys)[-8:]))
    while len(_pools) > WATCHED:
        _pools.popitem(last=False)


def pool_changed(pool: str) -> None:
    """A pool's variants changed, or its write ended: tell the prompts it serves."""
    prof, keys = _pools.get(str(pool), (None, set()))
    for key in list(keys):
        prompt_changed(key, prof)


def prompt_changed(key: Optional[str], profile_id: Optional[str]) -> None:
    """Tell the editor this prompt changed (safe from any thread)."""
    loop = _loop
    if not key or loop is None or loop.is_closed():
        return
    try:
        loop.call_soon_threadsafe(_queue, str(key), profile_id)
    except RuntimeError:   # the loop is shutting down
        pass


def _queue(key: str, profile_id: Optional[str]) -> None:
    global _flush
    _pending[(key, profile_id)] = None
    if _flush is None:
        _flush = asyncio.get_running_loop().call_later(GATHER, _send)


def _send() -> None:
    global _flush
    _flush = None
    out = list(_pending)
    _pending.clear()
    for key, profile_id in out:
        asyncio.ensure_future(_broadcast(key, profile_id))


async def _broadcast(key: str, profile_id: Optional[str]) -> None:
    try:
        from utils import websocket
        data: Dict[str, Any] = {"key": key}
        if profile_id:
            data["profile_id"] = profile_id
        await websocket.ws_manager.broadcast(EVENT, data)
    except Exception as e:
        log.debug(f"[fluent] couldn't send {EVENT} for {key}: {e}")


__all__ = ["EVENT", "pool_changed", "prompt_changed", "watch"]
