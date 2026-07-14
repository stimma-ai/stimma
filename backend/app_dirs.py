"""
Platform-specific application directory paths.

Uses a two-level directory scheme: bundle ID (release channel) + sandbox (isolated instance).

    <os-data-root>/<bundle-id>/<sandbox>/

Environment variables STIMMA_DATA_DIR and STIMMA_CACHE_DIR override all derivation.

Platform conventions:
- macOS: ~/Library/Application Support/<bundle-id>/<sandbox>/
- Windows: %LOCALAPPDATA%/<bundle-id>/<sandbox>/
- Linux: ~/.local/share/<bundle-id>/<sandbox>/
"""
import os
import platform
from pathlib import Path
from typing import Optional

from app_context import get_bundle_id, get_sandbox


def _os_data_root() -> Path:
    """Return the OS-specific root for application data."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support"
    elif system == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(localappdata)
    else:
        xdg_data = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        return Path(xdg_data)


def _os_cache_root() -> Path:
    """Return the OS-specific root for cache data."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Caches"
    elif system == "Windows":
        localappdata = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        return Path(localappdata)
    else:
        xdg_cache = os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))
        return Path(xdg_cache)


def get_data_dir() -> Path:
    """Return the sandbox-specific data directory.

    Checks STIMMA_DATA_DIR env var first (highest precedence), then derives
    from bundle_id + sandbox.
    """
    override = os.environ.get("STIMMA_DATA_DIR")
    if override:
        return Path(override)
    return _os_data_root() / get_bundle_id() / get_sandbox()


def get_cache_dir() -> Path:
    """Return the sandbox-specific cache directory.

    Checks STIMMA_CACHE_DIR env var first, then derives from bundle_id + sandbox.
    """
    override = os.environ.get("STIMMA_CACHE_DIR")
    if override:
        return Path(override)
    return _os_cache_root() / get_bundle_id() / get_sandbox()


def get_bundle_data_root() -> Path:
    """Return the bundle-level data directory (parent of all sandboxes).

    Used by fork commands to list/create/destroy sandboxes.
    """
    return _os_data_root() / get_bundle_id()


def get_bundle_cache_root() -> Path:
    """Return the bundle-level cache directory (parent of all sandboxes)."""
    return _os_cache_root() / get_bundle_id()


def get_all_stimma_owned_roots() -> list[Path]:
    """Return private data/cache roots that Sources must never scan.

    Include every release channel, not only the running one, so a broad Source
    such as the home directory cannot import another Stimma install's managed
    objects. Explicit environment overrides are included as well.
    """
    from app_context import (
        BUNDLE_ID_BETA,
        BUNDLE_ID_CANARY,
        BUNDLE_ID_DEBUG,
        BUNDLE_ID_STABLE,
    )

    bundle_ids = {
        BUNDLE_ID_STABLE,
        BUNDLE_ID_BETA,
        BUNDLE_ID_CANARY,
        BUNDLE_ID_DEBUG,
        get_bundle_id(),
    }
    roots = [get_data_dir(), get_cache_dir()]
    roots.extend(_os_data_root() / bundle_id for bundle_id in bundle_ids)
    roots.extend(_os_cache_root() / bundle_id for bundle_id in bundle_ids)
    return list(dict.fromkeys(root.expanduser().resolve(strict=False) for root in roots))


def get_source_excluded_roots() -> list[Path]:
    """Return every filesystem root that must remain invisible to Sources."""
    import tempfile

    roots = [
        *get_all_stimma_owned_roots(),
        Path(tempfile.gettempdir()).resolve(strict=False),
    ]
    return list(dict.fromkeys(roots))


def get_config_path() -> Path:
    """Return path to config.yaml inside data directory."""
    return get_data_dir() / "config.yaml"


def get_profile_dir(profile_id: Optional[str] = None) -> Path:
    """Return profile-specific directory inside data directory."""
    if not profile_id:
        raise ValueError("profile_id is required")
    return get_data_dir() / profile_id


def get_database_path(profile_id: Optional[str] = None) -> Path:
    """Return database path for a profile."""
    if not profile_id:
        raise ValueError("profile_id is required")
    return get_profile_dir(profile_id) / "stimma_v1.db"


def get_managed_staging_dir(
    profile_id: Optional[str] = None,
    category: str = "generated",
) -> Path:
    """Return an app-owned transient directory outside watched sources."""
    if category not in {"generated", "uploads"}:
        raise ValueError(f"Unsupported staging category: {category}")
    return get_profile_dir(profile_id) / "staging" / category


def get_thumbnail_cache_dir() -> Path:
    """Return thumbnail cache directory."""
    return get_cache_dir() / "thumbnails"


def get_uploads_dir() -> Path:
    """Return temporary uploads directory in cache."""
    return get_cache_dir() / "uploads"
