"""Scope saved views to projects and retain deleted views.

Revision ID: sv01
Revises: mcp02
"""
from alembic import op
import sqlalchemy as sa

revision = "sv01"
down_revision = "mcp02"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("saved_views", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("project_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_saved_views_project", "projects", ["project_id"], ["id"])
        batch.create_index("ix_saved_views_project_id", ["project_id"])


def downgrade():
    with op.batch_alter_table("saved_views", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_index("ix_saved_views_project_id")
        batch.drop_constraint("fk_saved_views_project", type_="foreignkey")
        batch.drop_column("deleted_at")
        batch.drop_column("project_id")
