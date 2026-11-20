"""Agent timers: wake-ups the chat agent sets for itself.

Revision ID: timers01
Revises: mact01

One-shot or repeating. When one comes due, the chat gets a timer message
that starts a turn, so the agent can check back on work or keep going on a
task the user asked it to run for hours.
"""
from alembic import op
import sqlalchemy as sa

revision = "timers01"
down_revision = "mact01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "agent_timers" in inspector.get_table_names():
        return
    op.create_table(
        "agent_timers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chat_id", sa.Integer(), sa.ForeignKey("chats.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("interval_s", sa.Integer(), nullable=False),
        sa.Column("repeat", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fire_at", sa.DateTime(), nullable=False),
        sa.Column("fire_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.Column("end_reason", sa.String(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_agent_timers_chat_id", "agent_timers", ["chat_id"])
    op.create_index("ix_agent_timers_fire_at", "agent_timers", ["fire_at"])
    op.create_index("ix_agent_timers_ended_at", "agent_timers", ["ended_at"])


def downgrade():
    op.drop_table("agent_timers")
