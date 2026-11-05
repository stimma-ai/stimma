"""Make Flows opt-in, preserving access for existing flow owners."""
from alembic import op
import sqlalchemy as sa

revision = "flowsopt01"
down_revision = "msidecars01"
branch_labels = None
depends_on = None


def upgrade():
    # One snapshot per profile DB. Later flow creation must never change an
    # explicit opt-out, and a profile without flows starts with the feature off.
    op.get_bind().execute(sa.text("""
        INSERT INTO user_preferences (key, value, updated_at)
        SELECT 'experimental_flows',
               CASE WHEN EXISTS (SELECT 1 FROM flows WHERE deleted_at IS NULL)
                    THEN '{"enabled": true}' ELSE '{"enabled": false}' END,
               CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM user_preferences WHERE key = 'experimental_flows'
        )
    """))


def downgrade():
    op.get_bind().execute(sa.text(
        "DELETE FROM user_preferences WHERE key = 'experimental_flows'"
    ))
