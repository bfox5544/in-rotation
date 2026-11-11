"""Remove the Spotify import (owner request 2026-11-04, ADR 0023 withdrawn): drop spotify_imports.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("spotify_imports")


def downgrade() -> None:
    op.create_table(
        "spotify_imports",
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=True, unique=True),
        sa.Column("code_verifier", sa.String(128), nullable=True),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("albums", sa.JSON, nullable=False),
        sa.Column("found", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
