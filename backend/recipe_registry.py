"""In-memory registry of active RecipeRuntimes.

Phase 4 uses this to route task-resolution API calls back to the running
scheduler for a given recipe_id. It is a minimal module-level singleton —
Phase 5/6 may grow it into a more complete runtime manager (lifecycle on
recipe create/start/pause/app-restart, etc.).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Iterable, Optional

if TYPE_CHECKING:
    from recipe_runtime.runtime import RecipeRuntime


_RUNTIMES: dict[int, "RecipeRuntime"] = {}


def register(recipe_id: int, runtime: "RecipeRuntime") -> None:
    _RUNTIMES[recipe_id] = runtime


def unregister(recipe_id: int) -> None:
    _RUNTIMES.pop(recipe_id, None)


def get_runtime(recipe_id: int) -> Optional["RecipeRuntime"]:
    return _RUNTIMES.get(recipe_id)


def active_recipe_ids() -> list[int]:
    return list(_RUNTIMES.keys())


def all_runtimes() -> Iterable["RecipeRuntime"]:
    return list(_RUNTIMES.values())


def reset() -> None:
    """Test-only: clear the registry. Production code never needs this."""
    _RUNTIMES.clear()
