"""Restore non-reusable identities after SQLite batch table rebuilds.

Revision ID: cache01
Revises: sv01

SQLite reflection does not retain sqlite_autoincrement. Several historical
batch migrations silently removed it, allowing new media and jobs to inherit
deleted identities (including managed-storage paths and client cache entries).
"""
from alembic import op
import sqlalchemy as sa

revision = "cache01"
down_revision = "sv01"
branch_labels = None
depends_on = None


# These tables lost the guarantee declared by their ORM models.
TABLES = ("media_items", "generation_jobs", "chat_items", "presets", "cached_provider_tools")


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    names = set(inspector.get_table_names())
    for name in TABLES:
        schema = connection.execute(sa.text(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"
        ), {"name": name}).scalar_one()
        high_water = connection.exec_driver_sql(f'SELECT COALESCE(MAX(id), 0) FROM "{name}"').scalar_one()
        sequence = connection.execute(sa.text(
            "SELECT MAX(seq) FROM sqlite_sequence WHERE name=:name"
        ), {"name": name}).scalar_one()
        high_water = max(high_water, sequence or 0)

        # Deleted Media IDs remain in durable delete receipts and other weak
        # references after the row is gone. Do not allocate those IDs again.
        references = []
        for child in names:
            for fk in inspector.get_foreign_keys(child):
                if fk["referred_table"] == name and fk["referred_columns"] == ["id"]:
                    references.append((child, fk["constrained_columns"][0]))
        if name == "media_items":
            references.extend((
                ("delete_operation_items", "media_id"),
                ("generation_jobs", "result_media_id"),
                ("generation_jobs", "batch_output_set_id"),
            ))
        for child, column in references:
            referenced = connection.exec_driver_sql(
                f'SELECT COALESCE(MAX("{column}"), 0) FROM "{child}"'
            ).scalar_one()
            high_water = max(high_water, referenced)

        if "AUTOINCREMENT" not in schema.upper():
            # Batch reflection preserves columns, constraints and indexes.
            # Triggers are not reflected, so carry their original SQL across.
            triggers = connection.execute(sa.text(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=:name"
            ), {"name": name}).scalars().all()
            with op.batch_alter_table(
                name, recreate="always", table_kwargs={"sqlite_autoincrement": True},
            ):
                pass
            for sql in triggers:
                connection.exec_driver_sql(sql)

        # Rebuilding from surviving rows alone loses the prior high-water mark.
        connection.execute(sa.text("DELETE FROM sqlite_sequence WHERE name=:name"), {"name": name})
        connection.execute(sa.text(
            "INSERT INTO sqlite_sequence (name, seq) VALUES (:name, :seq)"
        ), {"name": name, "seq": high_water})


def downgrade() -> None:
    # Retaining AUTOINCREMENT is backwards compatible and avoids reviving IDs.
    pass
