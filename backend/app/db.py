"""Connection to the user-data database (PostgreSQL from M6, ADR 0006).

INROTATION_DATABASE_URL picks the database; the default is the docker-compose Postgres with its
dev-only credentials. Any SQLAlchemy URL works, so tests run on a temporary SQLite file unless
INROTATION_TEST_DATABASE_URL points them at Postgres. The schema is owned by Alembic
(backend/migrations); the API refuses to start on a database that is not at the latest revision.
"""
import os
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

BACKEND = Path(__file__).resolve().parent.parent
DEFAULT_URL = "postgresql+psycopg://in_rotation:in_rotation_dev@localhost:5432/in_rotation"   # dev only


def database_url() -> str:
    return os.environ.get("INROTATION_DATABASE_URL", DEFAULT_URL)


def alembic_config(url: str | None = None) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.set_main_option("sqlalchemy.url", (url or database_url()).replace("%", "%%"))
    return cfg


@lru_cache
def get_engine() -> Engine:
    url = database_url()
    if url.startswith("sqlite"):
        # FastAPI runs sync dependencies on worker threads; SQLite also needs foreign keys switched on.
        engine = create_engine(url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys = ON"))
        return engine
    return create_engine(url, pool_pre_ping=True)


@lru_cache
def _sessions() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


def check_schema() -> None:
    """Fail at startup, with the fix, if the database is unreachable or not migrated."""
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    try:
        with get_engine().connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
    except Exception as e:
        raise RuntimeError(f"Can't connect to the database ({e.__class__.__name__}). Start Postgres with "
                           "`docker compose up -d db` from the repo root, or set INROTATION_DATABASE_URL.") from e
    if current != head:
        raise RuntimeError(f"Database schema is at {current or 'nothing'}, expected {head}. "
                           "Run `alembic upgrade head` from backend/.")


def get_db() -> Iterator[Session]:
    with _sessions()() as db:
        yield db
        db.commit()


# scope="function" commits before the response is sent. With the default (request) scope FastAPI
# sends the 204 first, so a client's next request could miss the write (seen in the M6 smoke test).
DB = Annotated[Session, Depends(get_db, scope="function")]
