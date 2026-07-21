"""In-memory registry of active FlowRuntimes.

Phase 4 uses this to route task-resolution API calls back to the running
scheduler for a given flow_id. It is a minimal module-level singleton —
Phase 5/6 may grow it into a more complete runtime manager (lifecycle on
flow create/start/pause/app-restart, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

from core.profile_context import get_current_profile

if TYPE_CHECKING:
    from flow_runtime.runtime import FlowRuntime


_RUNTIMES: dict[tuple[str, int], "FlowRuntime"] = {}


def _key(flow_id: int) -> tuple[str, int]:
    """Flow IDs are profile-local, so every registry lookup must be too."""
    return (get_current_profile(), flow_id)


def register(flow_id: int, runtime: "FlowRuntime") -> None:
    _RUNTIMES[_key(flow_id)] = runtime


def unregister(flow_id: int) -> None:
    _RUNTIMES.pop(_key(flow_id), None)


def get_runtime(flow_id: int) -> Optional["FlowRuntime"]:
    return _RUNTIMES.get(_key(flow_id))


def active_flow_ids() -> list[int]:
    profile_id = get_current_profile()
    return [flow_id for (profile, flow_id) in _RUNTIMES if profile == profile_id]


def all_runtimes() -> Iterable["FlowRuntime"]:
    return list(_RUNTIMES.values())


def reset() -> None:
    """Test-only: clear the registry. Production code never needs this."""
    _RUNTIMES.clear()
