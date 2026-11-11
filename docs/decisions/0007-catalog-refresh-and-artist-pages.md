# 0007: Catalog refresh, stable album ids, and artist pages (M7 remainder)

Status: accepted by the owner (2026-11-02).

## Refresh job (`python -m ingest.refresh`)
MusicBrainz publishes new dumps twice a week. The job turns "download and re-run two scripts" into one command that is safe to schedule:
1. **Check.** Compare `json-dumps/LATEST` with `dump_dir` in `data/musicbrainz/ingest_meta.json`. `--check` only reports, and exits 10 when a newer dump exists.
2. **Download** `release-group.tar.xz` (1.2 GB) into `data/musicbrainz/staging/` and verify it against that folder's `SHA256SUMS`. A mismatch deletes the file and stops.
   - `--core` also refreshes the core tables from the full export (7.7 GB).
   - Without it, the current core tables are reused. That is the default because the core tables only add release links and redirects; a few days' lag costs a handful of matches.
3. **Build** the new catalog beside the live one (`catalog.db.new`).
4. **Gate.** Refuse to swap if listening coverage fell by more than 1 point, or the catalog shrank by more than 2%. Either would point to a broken or partial dump.
   - When refused, the live catalog is untouched and the candidate files are kept for inspection.
   - `--force` overrides the gate.
5. **Swap.** `catalog.db` → `catalog.db.prev`, new → `catalog.db`, and the new Parquet and metadata replace the old. Downloads are deleted unless `--keep-downloads`.

The model is not retrained. Only the catalog and the ID map change, so the API's model check still passes.

**The running API keeps the old catalog until it restarts.** It opens the file at startup, and the swap is a rename, so an open process keeps reading the old file safely. Hot reload was left out: restarting is simple and takes about 4 seconds.

**Scheduling** is left to the machine: cron or launchd (README has an example). Nothing is installed automatically.

## Stable album ids across refreshes
Album ids are release-group MBIDs. When MusicBrainz merges two release groups, one MBID is retired behind a redirect, and a saved favorite under it would silently disappear.
- `ingest.catalog` now loads `release_group_gid_redirect` from the core dump into `album_redirects(old_id, album_id)`. On the 2026-10-27 core dump that is 84,864 redirects into catalog albums.
- The API resolves redirects everywhere it reads ids (`Catalog.canonical`): album pages, libraries, recommendation seeds and exclusions.
- New saves always store the current id. Removing an album also deletes rows saved under its old ids (`Catalog.saved_as`).
- **User rows are never rewritten**, so the catalog stays a separate, read-only file and a refresh never touches user data.
- **Albums that leave the catalog with no redirect** (deleted in MusicBrainz, or no longer matched) are counted as `retired_albums` in the refresh report. Saved rows for them stay in the database but are not shown.

## Artist pages
- `GET /api/artists/{id}` returns the artist, studio albums (primary type Album, no secondary types) and other releases (EPs, singles, live albums, compilations), each most-listened first.
- It also returns **related artists**: the engine is queried with the artist's five most-listened albums, excluding all of theirs, with at most one album per artist. Each related artist is shown through that album. On the full data this takes about 20 ms; for Radiohead it gives The Smile, Thom Yorke, Atoms for Peace, Jeff Buckley, Car Seat Headrest, Slowdive, Pink Floyd and Elliott Smith.
- `GET /api/artists?q=` searches artist names and aliases with FTS5 word prefixes, most-listened first. The search page shows matching artists as chips above the album results.
- Albums now carry `artistId` (the first credited artist), and artist names on cards and album pages link to the artist page.
- The catalog file gains `artists.popularity`, `artist_search` and `album_redirects`. `catalog_meta.schema_version` is now 2, and the API refuses an older catalog with the rebuild command.
- **Limits:** the page covers only albums in the catalog, which means albums someone in the dataset listened to, so discographies are incomplete. "Related" is listener overlap, not a curated relation.
