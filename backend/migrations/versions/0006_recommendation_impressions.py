"""Albums recommended to each user, for the Insights tab's recommendation stats (ADR 0017).

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_impressions",
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("album_id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("shown_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("recommendation_impressions")
