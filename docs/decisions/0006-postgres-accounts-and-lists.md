# 0006: PostgreSQL user data, optional accounts, and lists (M6)

Status: accepted by the owner (2026-11-02). `user_favorites` was later dropped (ADR 0009).

## Storage
- **User data moves to PostgreSQL** (the `docker-compose.yml` service), through **SQLAlchemy 2** (`app/schema.py`, `app/db.py`) with **Alembic** migrations (`backend/migrations`). The driver is psycopg 3.
- `INROTATION_DATABASE_URL` selects the database. The default is the compose database with its dev-only credentials.
- **The API refuses to start** when the database is unreachable or not at the latest migration, and the error names the fix (`docker compose up -d db`, `alembic upgrade head`).
- The code is dialect-neutral, so tests run on a temporary SQLite file by default. `INROTATION_TEST_DATABASE_URL` runs the same tests on Postgres; each test empties that database with `alembic downgrade base`. Both were run for this milestone. An autogenerate comparison against Postgres found no drift between the models and migration 0001.
- **The catalog stays in SQLite** (`data/catalog.db`, ADR 0005). It is derived, read-only and rebuilt in 30 seconds, and FTS5 search works well. Moving it to Postgres with `pg_trgm` is left for when deployment (M9) needs a single database.
- **Old development data is not migrated.** `backend/data/in_rotation.db` held favorites under the seed slugs, which stopped resolving in M5. Browsers holding an old token get a 401 and start a new session automatically.

## Tables (migration 0001)
`users(id, email NULL UNIQUE, password_hash NULL, created_at)`, `sessions(token_hash PK, user_id, created_at)`, `user_favorites(user_id, album_id, created_at)`, `lists(id, user_id, name, kind, created_at)` and `list_items(list_id, album_id, added_at)`. Deleting a user cascades to the other four tables. Differences from the original M6 target schema:
- **A `sessions` table replaces `users.token_hash`.** One account can then be signed in on several browsers, and signing out ends only one of them.
- **Listen later is a list** of kind `listen_later`. A partial unique index allows one per user, and it is created along with the user. Custom lists use kind `custom`.
- **Not yet added:** `onboarded_at`, `list_items.position` (manual ordering) and `user_ratings`. Ratings belong to M8, and no feature reads the other two yet.

## Accounts
- **Sign-up attaches** an email and password to the current anonymous user (`POST /api/account/register`), so everything saved is kept. Emails are stored lowercased.
- **Sign-in** (`POST /api/account/login`) issues a new session for the account. If the browser had an anonymous library, its favorites, listen-later albums and lists are **merged** into the account, skipping duplicates, and the anonymous user is deleted.
- **Sign-out** (`POST /api/account/logout`) deletes that session. The browser then starts a new, empty anonymous library.
- **Passwords** are hashed with stdlib `hashlib.scrypt` (n=2^14, r=8, p=1, 16-byte salt, constant-time compare), so no new dependency is needed. The minimum length is 8.
- Unknown emails and wrong passwords get the same message and take the same time, because unknown emails are checked against a dummy hash.
- **Not done:** email verification, password reset, rate limiting of sign-in attempts and session expiry. Rate limiting and expiry are needed before any public deployment (M9). Without a reset flow, a forgotten password loses the account.

## Lists
- The routes are `POST /api/me/lists`, `PATCH`/`DELETE /api/me/lists/{id}`, and `PUT`/`DELETE /api/me/lists/{id}/albums/{album_id}`.
- `GET /api/me/library` now also returns `lists`. Another user's list returns 404.
- **Recommendations exclude albums on any list,** not just favorites and listen later, following the "already listed" exclusion rule for recommendations.

## A bug fixed along the way: commits after the response
FastAPI (0.162 here) runs the cleanup after a `yield` dependency **after sending the response**. The M2-era `get_db` committed in that cleanup, so a client could receive `204` before the write was committed. The M6 smoke test showed the effect: a favorite saved just before sign-in was missing after the merge.

`app/db.py` now declares the session as `Depends(get_db, scope="function")`, which commits before the response is sent, and `requirements.txt` requires `fastapi>=0.121`. After the change, 20 repeated live runs lost nothing. The race was only reproduced live, so there is no regression test for it; the in-process TestClient did not show it.
