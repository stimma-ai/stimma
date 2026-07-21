"""On-disk layout for profile-scoped flows and the global equation store."""

from __future__ import annotations

from pathlib import Path

# Import the module, not the bound function, so test patches applied via
# patch.multiple("app_dirs", ...) take effect here too.
import app_dirs
from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)

_MIGRATION_OWNER_FILE = "flow_dir_migration_owner"


def _merge_legacy_root(source: Path, target: Path) -> None:
    """Move a legacy flow root into ``target`` without overwriting data.

    The usual migration is a single directory rename. If a prior interrupted
    migration already populated ``target``, move only non-conflicting children
    and leave collisions at the legacy path for manual recovery. This keeps the
    startup migration idempotent and strictly non-destructive.
    """
    if not source.is_dir() or source == target:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            source.rename(target)
            log.info("migrated legacy flow data dir: %s -> %s", source, target)
            return
        if not target.is_dir():
            log.warning(
                "legacy flow data migration skipped; target is not a directory: %s",
                target,
            )
            return

        conflicts: list[str] = []
        moved = 0
        for child in source.iterdir():
            destination = target / child.name
            if destination.exists():
                conflicts.append(child.name)
                continue
            child.rename(destination)
            moved += 1
        if not any(source.iterdir()):
            source.rmdir()
        if moved:
            log.info(
                "merged %d legacy flow entries into profile flow dir: %s",
                moved,
                target,
            )
        if conflicts:
            log.warning(
                "legacy flow data migration left %d conflicting entries in %s: %s",
                len(conflicts),
                source,
                ", ".join(sorted(conflicts)),
            )
    except Exception as e:  # noqa: BLE001 — best-effort; never block startup
        log.warning("legacy flow data migration skipped (%s -> %s): %s", source, target, e)


def _legacy_migration_owner(data_dir: Path, requested_profile_id: str) -> str | None:
    """Persist and return the one profile allowed to adopt legacy flow data."""
    owner_path = data_dir / _MIGRATION_OWNER_FILE
    try:
        if owner_path.exists():
            owner = owner_path.read_text().strip()
            if not owner:
                log.warning("legacy flow migration owner file is empty: %s", owner_path)
                return None
            return owner

        owner_path.parent.mkdir(parents=True, exist_ok=True)
        pending_path = owner_path.with_name(f"{owner_path.name}.pending")
        pending_path.write_text(f"{requested_profile_id}\n")
        pending_path.replace(owner_path)
        return requested_profile_id
    except OSError as e:
        # Never move data unless ownership was made durable first. Otherwise a
        # later startup could choose a different profile for a partial retry.
        log.warning("could not persist legacy flow migration owner: %s", e)
        return None


def migrate_legacy_flow_dirs(target_profile_id: str | None = None) -> str | None:
    """Move pre-profile flow directories into one selected profile.

    Older releases stored every profile's flow data under the sandbox-wide
    ``flows/`` directory (and, earlier, ``recipes/``). Flow IDs are only unique
    inside a profile database, so that layout allowed profiles to collide.

    Startup selects the profile with the most Assets and passes it here. Both
    legacy roots are then merged into that profile's private flow root. Safe to
    call repeatedly; existing destination entries are never overwritten.
    """
    requested_profile_id = target_profile_id or get_current_profile()
    data_dir = app_dirs.get_data_dir()
    legacy_roots = (data_dir / "flows", data_dir / "recipes")
    owner_path = data_dir / _MIGRATION_OWNER_FILE
    if owner_path.exists():
        profile_id = _legacy_migration_owner(data_dir, requested_profile_id)
    else:
        requested_recipes = (
            app_dirs.get_profile_dir(profile_id=requested_profile_id) / "recipes"
        )
        if not any(root.is_dir() for root in (*legacy_roots, requested_recipes)):
            return requested_profile_id
        profile_id = _legacy_migration_owner(data_dir, requested_profile_id)
    if profile_id is None:
        return None
    profile_recipes = app_dirs.get_profile_dir(profile_id=profile_id) / "recipes"
    if not any(root.is_dir() for root in (*legacy_roots, profile_recipes)):
        return profile_id
    if profile_id != requested_profile_id:
        log.info(
            "using persisted legacy flow migration owner",
            profile=profile_id,
            requested_profile=requested_profile_id,
        )
    target = get_flows_root(profile_id)
    for legacy_root in legacy_roots:
        _merge_legacy_root(legacy_root, target)
    # Defensive support for an intermediate profile-scoped recipes layout.
    _merge_legacy_root(profile_recipes, target)
    return profile_id


def get_flows_root(profile_id: str | None = None) -> Path:
    """Return the current profile's private flow root."""
    resolved_profile_id = profile_id or get_current_profile()
    return app_dirs.get_profile_dir(profile_id=resolved_profile_id) / "flows"


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
