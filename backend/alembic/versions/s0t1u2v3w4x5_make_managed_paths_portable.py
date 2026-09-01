"""Store managed Media paths relative to their profile directory.

Revision ID: s0t1u2v3w4x5
Revises: r9s0t1u2v3w4
"""

from pathlib import PurePosixPath

from alembic import op
import sqlalchemy as sa


revision = "s0t1u2v3w4x5"
down_revision = "r9s0t1u2v3w4"
branch_labels = None
depends_on = None


def _safe_filename(original_filename: str | None, file_path: str) -> str:
    portable = (original_filename or file_path).replace("\\", "/")
    return PurePosixPath(portable).name or "payload"


def _normalized(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


def _relative_locator(value: str | None, profile_roots: set[str]) -> str | None:
    if not value:
        return value
    normalized = _normalized(value)
    for profile_root in sorted(profile_roots, key=len, reverse=True):
        if normalized == profile_root:
            return "."
        prefix = f"{profile_root}/"
        if normalized.startswith(prefix):
            return normalized[len(prefix):]
        data_root = profile_root.rsplit("/", 1)[0]
        data_prefix = f"{data_root}/"
        if normalized.startswith(data_prefix):
            return f"@data/{normalized[len(data_prefix):]}"
    return value


def upgrade() -> None:
    connection = op.get_bind()
    rows = list(connection.execute(sa.text("""
        SELECT m.id, m.file_path, m.original_filename
        FROM media_items AS m
        JOIN storage_objects AS s ON s.id = m.storage_object_id
        WHERE s.kind = 'managed'
    """)))
    profile_roots = set()
    for _media_id, file_path, _original_filename in rows:
        normalized = _normalized(file_path)
        marker = "/objects/"
        if marker in normalized:
            profile_roots.add(normalized.split(marker, 1)[0])

    for media_id, file_path, original_filename in rows:
        portable_path = (
            f"objects/media/{media_id}/"
            f"{_safe_filename(original_filename, file_path)}"
        )
        connection.execute(
            sa.text("UPDATE media_items SET file_path = :path WHERE id = :id"),
            {"path": portable_path, "id": media_id},
        )

    for table, column in (
        ("delete_operation_items", "file_path"),
        ("generation_jobs", "folder_path"),
        ("managed_artifacts", "locator"),
        ("media_lineage", "source_file_path"),
        ("projects", "root_path"),
        ("working_documents", "state_locator"),
    ):
        path_rows = list(connection.execute(sa.text(
            f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
        )))
        for rowid, value in path_rows:
            portable = _relative_locator(value, profile_roots)
            if portable != value:
                connection.execute(sa.text(
                    f"UPDATE {table} SET {column} = :path WHERE rowid = :rowid"
                ), {"path": portable, "rowid": rowid})

    # Thumbnail files are disposable machine-local cache. A copied cache index
    # cannot be trusted, and durable delete work can safely forget those paths.
    connection.execute(sa.text("DELETE FROM media_thumbnail_cache"))
    connection.execute(sa.text(
        "UPDATE delete_operation_items SET thumbnail_paths = NULL "
        "WHERE thumbnail_paths IS NOT NULL"
    ))


def downgrade() -> None:
    # Absolute paths are machine-specific and cannot be reconstructed safely.
    pass
