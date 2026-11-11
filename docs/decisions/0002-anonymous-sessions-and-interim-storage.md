# 0002: Anonymous sessions and interim storage (M2)

Status: accepted for M2. Storage and the single token per user are superseded by ADR 0006 (M6).

## Anonymous sessions
The first time the web app needs per-user data, it calls `POST /api/session`. The API creates a user row with no personal data and returns a random token. Only the SHA-256 hash of the token is stored. The browser keeps the token in `localStorage` (key `inrotation.token`) and sends it as `Authorization: Bearer <token>`.

- Clearing browser storage loses access to that library. This is accepted until real accounts exist.
- If the server no longer recognises a token (for example after a database reset), the client discards it and starts a new session once.
- M6 adds optional email sign-in by attaching credentials to the existing user row, so an anonymous library can be kept on sign-up.

## Interim storage
Per-user data lives in SQLite (`backend/data/in_rotation.db`, git-ignored) behind `app/db.py` so the M2 API can be tested without Docker. M6 moves it to PostgreSQL with SQLAlchemy and Alembic. The album catalog is still a JSON seed (`app/data/albums.json`) read by `app/catalog.py`; M7 replaces it with MusicBrainz-sourced rows.

## Placeholder recommendations
`GET /api/me/recommendations` returns genre-overlap results labelled `sample-genre-overlap`. M5 replaces the implementation behind the same endpoint.

## Rename and theme
The product name is "In Rotation" (the early working name was "Sleeve"). The UI uses a dark gray palette defined as CSS variables at the top of `web/src/styles.css`.
