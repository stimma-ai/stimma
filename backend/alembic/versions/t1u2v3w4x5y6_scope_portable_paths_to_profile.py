"""Scope portable paths to their owning profile.

Revision ID: t1u2v3w4x5y6
Revises: s0t1u2v3w4x5
"""

from pathlib import Path, PurePosixPath, PureWindowsPath

from alembic import op
import sqlalchemy as sa


revision = "t1u2v3w4x5y6"
down_revision = "s0t1u2v3w4x5"
branch_labels = None
depends_on = None


def _is_absolute(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


def _scoped(value: str | None, profile_id: str) -> str | None:
    if not value or value.startswith("@") or _is_absolute(value):
        return value
    normalized = PurePosixPath(value.replace("\\", "/")).as_posix()
    return f"@data/{profile_id}/{normalized}"


def upgrade() -> None:
    connection = op.get_bind()
    database = connection.engine.url.database
    if not database:
        raise RuntimeError("Cannot determine the profile database location")
    profile_id = Path(database).resolve().parent.name

    for table, column in (
        ("media_items", "file_path"),
        ("delete_operation_items", "file_path"),
        ("generation_jobs", "folder_path"),
        ("managed_artifacts", "locator"),
        ("media_lineage", "source_file_path"),
        ("projects", "root_path"),
        ("working_documents", "state_locator"),
    ):
        rows = list(connection.execute(sa.text(
            f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
        )))
        for rowid, value in rows:
            portable = _scoped(value, profile_id)
            if portable != value:
                connection.execute(sa.text(
                    f"UPDATE {table} SET {column} = :path WHERE rowid = :rowid"
                ), {"path": portable, "rowid": rowid})


def downgrade() -> None:
    # Removing the profile segment would restore the cross-profile ambiguity.
    pass
