"""Limits on new anonymous sessions and new accounts per device (rate_events), before the site went public
without its password (owner request 2026-11-10).

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rate_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("rate_events_by_key", "rate_events", ["action", "key", "at"])
    op.create_index("ix_rate_events_at", "rate_events", ["at"])


def downgrade() -> None:
    op.drop_index("ix_rate_events_at", table_name="rate_events")
    op.drop_index("rate_events_by_key", table_name="rate_events")
    op.drop_table("rate_events")
