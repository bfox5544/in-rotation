# 0005: MusicBrainz catalog, model-to-catalog mapping, and serving recommendations (M7 core + M5)

Status: accepted (2026-10-30). The owner chose to bring the MusicBrainz catalog (M7) forward, ahead of the recommendations API (M5) and PostgreSQL (M6). The 24-album seed catalog could not show what the engine does.

## Catalog source
- **Bulk data comes from the MusicBrainz dumps** at `data.metabrainz.org`, never the live API. Each download is checked against its `SHA256SUMS`. Two dumps are used:
  - `json-dumps/release-group.tar.xz` (1.2 GB): title, type, first release date, artist credits with artist IDs and aliases, genres. `ingest.musicbrainz` parses it to Parquet in about 6 minutes (4.6M release groups, 1.13M artists).
  - `fullexport/mbdump.tar.bz2` (7.7 GB, CC0 core tables): only `release`, `release_group` and `artist_credit` are extracted (about 7 minutes). They give release to release-group links and release titles.
- **Dataset MBIDs are release IDs.** None of the 312K MBIDs in the dataset is a release-group ID, and 99% resolve through the release table. This answers the open question from M3 without any live API calls; `probe_mbids` is no longer needed.
- **Licensing.** Core data is CC0. Genres come from MusicBrainz tags, listed as supplementary data (CC BY-NC-SA 3.0) on the MusicBrainz licence page. That is fine for this non-commercial project; review it before any other use. Covers were first linked from the Cover Art Archive (`/release-group/{mbid}/front-250`), not copied. ADR 0011 replaced that with a local cache, because the archive took 3-7 seconds per image. The site footer credits both.
- **Refresh:** download newer dumps (published twice a week), then re-run `ingest.musicbrainz` and `ingest.catalog`. There is no scheduler yet; that is part of the remaining M7 work.

## What the catalog contains
The release groups that at least one model album maps to: **389,474 albums**. These are the albums the engine can recommend and that user picks can influence. Albums the model has never seen are not in the catalog yet. That means no brand-new releases, which is the known snapshot limit; a content-based or recency path would add them.

## Mapping: model album to release group (`ingest.catalog`)
The first rule that hits wins:

| # | Rule | Albums | Share of listening |
|---|---|---|---|
| 1 | `exact`: dataset artist + title equal the credit + title, normalized | 353,580 | 83.6% |
| 2 | `mbid`: dataset MBID is a release in the group, **and the group credits the dataset artist** (name or alias) | 25,472 | 5.9% |
| 3 | `name`: same keys as the model (edition words stripped) | 1,564 | 0.3% |
| 4 | `release-name`: key of any release in the group ("Pure Heroine (Extended)") | 9,345 | 1.3% |
| 5 | `alias`: a single credited artist's alias ("GZA/Genius", "30 Seconds to Mars") | 8,194 | 0.4% |
| 6 | `co-artist`: any one credited artist ("Her Loss" credited only to Drake) | 12,473 | 0.8% |

- **Totals:** 410,628 of 633,053 model albums are matched, covering **92.3% of listening** and **97.1% of albums with 1,000+ listeners**. Unmatched albums stay in the model, where they still connect similar users, but they are never shown.
- **Keys** use the same DuckDB macros (`norm`, `strip_edition`) as `recs.preprocess`, imported from it, so the two sides cannot drift.
- **Why exact names outrank MBIDs:** where both hit, they agree 99.3% of the time. The disagreements were mostly wrong MBIDs in the dataset, such as Pink Floyd's *Dark Side of the Moon* pointing to Dream Theater's live cover and The Beatles' *Let It Be* to Laibach's. The artist check rejects those.
  - I tried also requiring the titles to be prefixes of each other, but that rejected correct edition MBIDs ("Emotion" → "E•MO•TION", "NewJeans 1st EP" → "New Jeans"), so it was dropped.
- **Ties:** when a key fits several release groups (16K albums, confidence 0.8), the winner is chosen by, in order:
  1. exact title match with the dataset ("The Dirty Version", not "The Dirty Version Instrumentals")
  2. primary type Album, then EP
  3. no secondary types (Compilation, Live and so on)
  4. earliest release
- **Known gaps:** about 7.7% of listening is unmatched. The largest remaining groups are:
  - K-pop titles with descriptors MusicBrainz leaves out ("Savage - The 1st Mini Album")
  - soundtracks credited differently
  - releases newer than the dump

  **Owner decision (2026-11-02): K-pop title descriptors are not stripped.** The identity rules stay as they are, and those albums stay unmatched.

## Storage
- `ingest.catalog` writes a **standalone SQLite file** (`data/catalog.db`, about 500 MB), which the API opens read-only.
  - Rebuilding it (about 30 seconds) never touches user data in `backend/data/in_rotation.db`.
  - Tables follow the M6 target schema (`albums`, `artists`, `album_artists`, `model_albums`, `album_id_map`), plus `album_genres`, `genres` and an FTS5 index (`album_search`).
- Album IDs are **release-group MBIDs**, so favorites saved under the old seed slugs ("illmatic") no longer resolve. That only affects development data.
- **Search** uses FTS5 word prefixes, accent-insensitive. It indexes the title, artist, genres and the dataset's own spellings, so "emotion" finds *E•MO•TION*. Ranking: title prefix first, then artist prefix, then everything else, each by listener count. A query that names a genre ("r&b") lists that genre.
- The API checks that the catalog was built from the loaded model (same album count) and refuses to start otherwise.
- M6 moves these tables to PostgreSQL, where `pg_trgm` can replace FTS5.

## Serving (`backend/app/engine.py`)
- The model is fitted once at startup: about 4 seconds and about 2.6 GB RAM. A recommendation request takes about 30 ms end to end.
- **Settings** are the `RecommenderConfig()` defaults (ADR 0004): linear weights, alpha 0.5, cosine, K 100, weighted sum, beta 0.25.
- **Query:** every model album mapped to each favorite, at weight 1.0. Editions and aliases of one catalog album all feed in.
- **Exclusions:** favorites and listen-later albums, at the model level, so excluded albums don't use up candidate slots.
- **Candidates and caps:** fetch 5x the requested number of model candidates, drop unmapped albums, merge duplicates that map to the same catalog album, then keep **at most 2 albums per primary artist**. The cap answers the same-artist concentration found in M4.
- **Fallback:** when no favorite maps to the model, the response is the most-listened catalog albums with `source: "popularity"`. Otherwise `source` is `"listening-data"`.
- **"Similar" on album pages** is the same engine queried with that one album ("Listeners also love"). It replaces the genre-overlap placeholder.
- **Not measured:** how much the artist cap and the merging change the M4 metrics. Measuring that means running the evaluation in catalog terms, which is a follow-up.
