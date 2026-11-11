"""Data migrations, run on the same database the API tests use (SQLite, or Postgres when configured)."""
from alembic import command
from sqlalchemy import create_engine, text

from app.db import alembic_config


def test_0003_turns_favorites_into_five_stars_and_doubles_ratings(database):
    cfg = alembic_config(database)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "0002")
    engine = create_engine(database)
    with engine.begin() as db:
        db.execute(text("INSERT INTO users (id, created_at) VALUES ('u1', CURRENT_TIMESTAMP)"))
        for album in ("fav-only", "fav-and-rated"):
            db.execute(text("INSERT INTO user_favorites VALUES ('u1', :a, CURRENT_TIMESTAMP)"), {"a": album})
        for album, stars in (("fav-and-rated", 2), ("rated-only", 4)):
            db.execute(text("INSERT INTO user_ratings VALUES ('u1', :a, :s, CURRENT_TIMESTAMP)"), {"a": album, "s": stars})
    command.upgrade(cfg, "head")
    with engine.connect() as db:
        got = dict(db.execute(text("SELECT album_id, half_stars FROM user_ratings")).all())
    engine.dispose()
    # A favorite becomes 5 stars unless the user had rated it: the explicit rating already won (ADR 0008).
    assert got == {"fav-only": 10, "fav-and-rated": 4, "rated-only": 8}
