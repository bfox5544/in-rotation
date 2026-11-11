"""Half-star ratings; favorites become 5-star ratings and the favorites table is dropped (ADR 0009).

Ratings are stored as half_stars, 1-10 (0.5 to 5 stars). Existing ratings are doubled. A favorite
the user had not rated becomes 10 half stars, which is how the engine already weighed it (ADR 0008),
so nobody's recommendations change. The table is rebuilt rather than altered so the same steps
run on PostgreSQL and on SQLite (tests).

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TS = sa.DateTime(timezone=True)


def _ratings_table(name: str, column: str, low: int, high: int) -> None:
    op.create_table(
        name,
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("album_id", sa.String(36), primary_key=True),
        sa.Column(column, sa.SmallInteger, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.CheckConstraint(f"{column} BETWEEN {low} AND {high}", name=f"{column}_range"),
    )


def _swap(new: str) -> None:
    op.drop_table("user_ratings")
    op.rename_table(new, "user_ratings")
    if op.get_bind().dialect.name == "postgresql":   # keep the usual constraint names after the rename
        op.execute(f"ALTER TABLE user_ratings RENAME CONSTRAINT {new}_pkey TO user_ratings_pkey")
        op.execute(f"ALTER TABLE user_ratings RENAME CONSTRAINT {new}_user_id_fkey TO user_ratings_user_id_fkey")


def upgrade() -> None:
    _ratings_table("user_ratings_new", "half_stars", 1, 10)
    op.execute("INSERT INTO user_ratings_new (user_id, album_id, half_stars, updated_at) "
               "SELECT user_id, album_id, rating * 2, updated_at FROM user_ratings")
    op.execute("""INSERT INTO user_ratings_new (user_id, album_id, half_stars, updated_at)
                  SELECT f.user_id, f.album_id, 10, f.created_at FROM user_favorites f
                  WHERE NOT EXISTS (SELECT 1 FROM user_ratings r WHERE r.user_id = f.user_id AND r.album_id = f.album_id)""")
    _swap("user_ratings_new")
    op.drop_table("user_favorites")


def downgrade() -> None:
    """Lossy: half stars round down to whole stars (minimum 1), and favorites come back empty,
    since a former favorite can't be told apart from a 5-star rating."""
    op.create_table(
        "user_favorites",
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("album_id", sa.String(36), primary_key=True),
        sa.Column("created_at", TS, nullable=False),
    )
    _ratings_table("user_ratings_old", "rating", 1, 5)
    op.execute("INSERT INTO user_ratings_old (user_id, album_id, rating, updated_at) "
               "SELECT user_id, album_id, CASE WHEN half_stars < 2 THEN 1 ELSE half_stars / 2 END, updated_at FROM user_ratings")
    _swap("user_ratings_old")
