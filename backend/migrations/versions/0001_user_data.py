"""User data: users, sessions, favorites, lists (M6, ADR 0006).

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("email", sa.String(254), unique=True),
        sa.Column("password_hash", sa.String(200)),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "sessions",
        sa.Column("token_hash", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "user_favorites",
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("album_id", sa.String(36), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_table(
        "lists",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("created_at", TS, nullable=False),
    )
    op.create_index("one_listen_later_per_user", "lists", ["user_id"], unique=True,
                    postgresql_where=sa.text("kind = 'listen_later'"), sqlite_where=sa.text("kind = 'listen_later'"))
    op.create_table(
        "list_items",
        sa.Column("list_id", sa.Integer, sa.ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("album_id", sa.String(36), primary_key=True),
        sa.Column("added_at", TS, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("list_items")
    op.drop_index("one_listen_later_per_user", table_name="lists")
    op.drop_table("lists")
    op.drop_table("user_favorites")
    op.drop_table("sessions")
    op.drop_table("users")
