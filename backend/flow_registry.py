"""In-memory registry of active FlowRuntimes.

Phase 4 uses this to route task-resolution API calls back to the running
scheduler for a given flow_id. It is a minimal module-level singleton —
Phase 5/6 may grow it into a more complete runtime manager (lifecycle on
flow create/start/pause/app-restart, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from flow_runtime.runtime import FlowRuntime


_RUNTIMES: dict[int, "FlowRuntime"] = {}


def register(flow_id: int, runtime: "FlowRuntime") -> None:
    _RUNTIMES[flow_id] = runtime


def unregister(flow_id: int) -> None:
    _RUNTIMES.pop(flow_id, None)


def get_runtime(flow_id: int) -> Optional["FlowRuntime"]:
    return _RUNTIMES.get(flow_id)


def active_flow_ids() -> list[int]:
    return list(_RUNTIMES.keys())


def all_runtimes() -> Iterable["FlowRuntime"]:
    return list(_RUNTIMES.values())


def reset() -> None:
    """Test-only: clear the registry. Production code never needs this."""
    _RUNTIMES.clear()
