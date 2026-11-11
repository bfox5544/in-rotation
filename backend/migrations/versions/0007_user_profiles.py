"""User profiles: username, display name, picture and visibility, private by default (ADR 0018).

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as t:
        t.add_column(sa.Column("username", sa.String(20), nullable=True))
        t.add_column(sa.Column("display_name", sa.String(40), nullable=True))
        t.add_column(sa.Column("avatar", sa.String(40), nullable=True))
        t.add_column(sa.Column("profile_public", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        t.create_unique_constraint("users_username_key", ["username"])


def downgrade() -> None:
    with op.batch_alter_table("users") as t:
        t.drop_constraint("users_username_key", type_="unique")
        t.drop_column("profile_public")
        t.drop_column("avatar")
        t.drop_column("display_name")
        t.drop_column("username")
