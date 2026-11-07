"""Contact sheet reviews: answers and comments keyed by sheet asset and component."""
from alembic import op
import sqlalchemy as sa

revision = "csheets01"
down_revision = "flowsopt01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "contact_sheet_reviews" in inspector.get_table_names():
        return
    op.create_table(
        "contact_sheet_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anchor", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("author_kind", sa.String(), nullable=False, server_default="owner"),
        sa.Column("author_name", sa.String(), nullable=True),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.Column("sent_value", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_contact_sheet_reviews_id", "contact_sheet_reviews", ["id"])
    op.create_index("ix_contact_sheet_reviews_asset_id", "contact_sheet_reviews", ["asset_id"])
    op.create_index("ix_contact_sheet_reviews_deleted_at", "contact_sheet_reviews", ["deleted_at"])
    op.create_index("idx_contact_sheet_reviews_anchor", "contact_sheet_reviews", ["asset_id", "anchor", "kind"])


def downgrade():
    op.drop_table("contact_sheet_reviews")
