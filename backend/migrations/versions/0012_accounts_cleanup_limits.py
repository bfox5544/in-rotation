"""Sign-in limits (login_failures) and users.last_seen_at for the anonymous-user cleanup (owner request 2026-11-07).

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE users SET last_seen_at = created_at")
    op.create_index("ix_users_last_seen_at", "users", ["last_seen_at"])
    op.create_table(
        "login_failures",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("login_failures_by_key", "login_failures", ["key", "at"])


def downgrade() -> None:
    op.drop_index("login_failures_by_key", table_name="login_failures")
    op.drop_table("login_failures")
    op.drop_index("ix_users_last_seen_at", table_name="users")
    op.drop_column("users", "last_seen_at")
