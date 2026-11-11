"""Daily Ask usage per account or browser and per device (ADR 0014 revision, owner request 2026-11-07).

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_usage",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("messages", sa.Integer, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("chat_usage")
