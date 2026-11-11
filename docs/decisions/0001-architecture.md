# Architecture decisions

Status of each: **accepted** unless noted.

## 1. Stack
Vite + React + TypeScript (web), FastAPI (API and recommender host), PostgreSQL (site data), DuckDB (offline preprocessing of the 500K-user dataset only). Reason: one Python process can load the model once; DuckDB is fast for the ~25M-row dataset but is not used for site data.

## 2. Repo layout
`web/` frontend, `backend/` API, `recs/` (added in M3/M4) pure-Python engine with no DB/HTTP imports, `data/` local dataset files (git-ignored), `docs/` decisions and notes.

## 3. Catalog is separate from the model
Site albums are keyed by MusicBrainz release-group ID where known. The model has its own integer index; a mapping table links the two (M5). Unmatched albums stay in the model but are never shown.

## 4. Placeholder artwork (M1)
Sample albums render generated SVG covers derived from a hash of the album ID, so the UI works offline and nothing is hotlinked. Real artwork arrives with the Cover Art Archive in M7; `Album.coverUrl` already takes precedence when present.

## 5. Open question for M3
`user_top_albums.mbid` is blank on some rows. Before relying on it, check whether it holds release, release-group or recording IDs and measure the blank rate.
