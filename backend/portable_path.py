"""Portable database locators for files owned by a Stimma profile."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.types import String, TypeDecorator


def _profile_dir() -> Path:
    import app_dirs
    from core.profile_context import get_current_profile

    return app_dirs.get_profile_dir(get_current_profile())


def contract_profile_path(value: str) -> str:
    """Store Stimma-owned paths without machine-specific directory prefixes.

    Data locators include the profile directory below ``@data``.  A bare path
    is ambiguous when work for multiple profiles runs concurrently, because a
    SQLAlchemy result processor has no reliable way to know which profile's
    database produced the value.
    """
    import app_dirs

    path = Path(value)
    if not path.is_absolute():
        path = _profile_dir() / path
    for marker, root in (
        ("@data", app_dirs.get_data_dir()),
        ("@cache", app_dirs.get_cache_dir()),
    ):
        try:
            return f"{marker}/{path.relative_to(root).as_posix()}"
        except ValueError:
            pass
    return str(path)


def expand_profile_path(value: str) -> str:
    """Resolve a persisted profile-relative locator for runtime file access."""
    path = Path(value)
    if path.is_absolute():
        return str(path)
    if path.parts and path.parts[0] == "@data":
        import app_dirs
        return str(app_dirs.get_data_dir().joinpath(*path.parts[1:]))
    if path.parts and path.parts[0] == "@cache":
        import app_dirs
        return str(app_dirs.get_cache_dir().joinpath(*path.parts[1:]))
    # Legacy fallback for databases that have not run the follow-up migration.
    return str(_profile_dir() / path)


class PortableProfilePath(TypeDecorator):
    """String column that contracts profile-owned paths only on persistence.

    External source paths remain absolute. Managed paths are expanded after a
    database read, so existing runtime callers continue to receive filesystem
    paths while the SQLite value remains portable between operating systems.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        # SQLAlchemy's startswith()/contains() auto-escaping can produce values
        # such as ``//root//folder/_name//``. Path normalization would destroy
        # those escape markers and change query semantics.
        if "%" in value or "//" in value[1:]:
            return value
        return contract_profile_path(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return expand_profile_path(value)
