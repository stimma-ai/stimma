"""On-disk layout for flows and the global equation store."""

from __future__ import annotations

from pathlib import Path

# Import the module, not the bound function, so test patches applied via
# patch.multiple("app_dirs", ...) take effect here too.
import app_dirs
from core.logging import get_logger

log = get_logger(__name__)


def _maybe_migrate_recipes_dir(data_dir: Path) -> None:
    """One-time: rename the legacy ``<data_dir>/recipes`` dir to ``flows``.

    The recipe→flow rename moved the DB table (alembic) but not the on-disk
    flow data. Without this, each flow's ``program.py`` / ``state.db`` stay under
    ``recipes/<id>/`` while the code now reads ``flows/<id>/``, so flows fail to
    load after the rename. Idempotent: a no-op once ``recipes/`` is gone.
    """
    recipes = data_dir / "recipes"
    if not recipes.is_dir():
        return
    flows = data_dir / "flows"
    try:
        if not flows.exists():
            recipes.rename(flows)
            log.info("migrated legacy recipes data dir to flows: %s", flows)
        elif flows.is_dir() and not any(flows.iterdir()):
            # flows/ exists but is empty (e.g. created before the data was there)
            for child in recipes.iterdir():
                child.rename(flows / child.name)
            recipes.rmdir()
            log.info("merged legacy recipes data dir into empty flows: %s", flows)
        # else: both populated — leave as-is (already migrated / ambiguous)
    except Exception as e:  # noqa: BLE001 — best-effort; never block startup
        log.warning("recipes->flows data dir migration skipped (%s): %s", data_dir, e)


def migrate_legacy_flow_dirs() -> None:
    """Run the legacy ``recipes/`` → ``flows/`` data-dir migration at startup.

    Safe to call repeatedly; a no-op once migrated. ``get_flows_root`` also runs
    it lazily, but calling it explicitly at startup migrates sandboxes that have
    no running flows to recover.
    """
    _maybe_migrate_recipes_dir(app_dirs.get_data_dir())


def get_flows_root() -> Path:
    data_dir = app_dirs.get_data_dir()
    _maybe_migrate_recipes_dir(data_dir)
    return data_dir / "flows"


def get_flow_dir(flow_id: int) -> Path:
    return get_flows_root() / str(flow_id)


def get_flow_state_db_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "state.db"


def get_flow_program_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "program.py"


def get_flow_program_base_path(flow_id: int) -> Path:
    """program_base.py is only present on forks (snapshot of parent at fork time)."""
    return get_flow_dir(flow_id) / "program_base.py"


def get_flow_resources_dir(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "resources"


def get_flow_metadata_path(flow_id: int) -> Path:
    return get_flow_dir(flow_id) / "metadata.json"


def get_equation_store_dir() -> Path:
    return app_dirs.get_data_dir() / "equation_store"


def get_equation_store_db_path() -> Path:
    return get_equation_store_dir() / "equations.db"


def get_equation_store_blobs_dir() -> Path:
    return get_equation_store_dir() / "blobs"
