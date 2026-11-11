# 0013: Track lists on album pages

Status: accepted (2026-11-02, owner request: "Add track listing to each album page").

## Source: the core dump, offline
Track lists come from the MusicBrainz core dump the catalog already uses (ADR 0005), not the live API:
- **Tables:** `medium`, `track` and `medium_format`, extracted from `mbdump.tar.bz2` next to the release tables. `track` is 7.9 GB uncompressed, about 10 minutes to extract.
- **Why not the live API:** at 1 request per second, with two calls per album, a cold album page would wait seconds, and the site would depend on MusicBrainz being up. Offline keeps every page a local lookup (about 10 ms) and fits the refresh job.
- `ingest.refresh --core` now extracts the three tables too. Without `--core` the existing ones are reused, as for the other core tables.

## Which release
An album here is a MusicBrainz release group, which holds many releases (editions) whose tracks differ: deluxe bonus tracks, regional extras, a DVD in the box. One release is shown, chosen in `ingest.catalog.tracklists()`:
1. **Pool:** the group's official releases, or all of them when none is official.
2. **Track count:** the most common audio track count wins, so the standard edition beats a lone deluxe edition. Ties go to the shorter list.
3. **Format:** a release on CD or digital media wins next, so tracks are numbered 1, 2, 3 and not cassette or vinyl sides (OK Computer had picked a cassette before this rule).
4. **Age:** the release MusicBrainz has had longest (lowest internal id) wins last.

**Left out:**
- Video media (DVD, Blu-ray, VHS and similar), so a bonus DVD doesn't add "music video" tracks.
- Data tracks.

**Track artists** are kept only when they differ from the release's credit, for guests ("Beyoncé feat. Jack White") and compilations.

## Storage and API
- `album_tracks(album_id, release_id, media)` in `data/catalog.db`: one row per album with the media as compact JSON (`[number, title, artist or null, length ms or null]` per track).
- The catalog format moves to `schema_version` 3, and the API refuses older catalog files with the rebuild command.
- The whole catalog build now takes about 53 s (about 40 s before).
- **Size:** 389,074 of 389,550 albums (99.97% of listening) have a list. The file grew from 585 MB to 893 MB.
- `GET /api/albums/{id}` returns `tracklist: {releaseId, discs: [{position, format, title, tracks: [{number, title, artist, seconds}]}]}`, or null.

## Album page
- A Tracks section sits under the album's buttons.
  - **Summary line:** track count and running time. The running time appears only when every track has a length.
  - **Discs:** each gets a "Disc N" heading when there are several.
  - **Tracks:** each shows its number, title and m:ss length, with guest credits under the title.
- "Track list from MusicBrainz" links to the release used, which credits the source and shows which edition this is.

## Limits
- The chosen edition can still differ from what a listener knows: an album whose only official releases are expanded reissues shows the expanded list.
- Track counts come from MusicBrainz's `track_count`, which includes data tracks. A disc with an enhanced-CD data track counts one extra when editions are compared, though the data track itself is never shown.
- Track titles are MusicBrainz data (CC0); nothing new to license.
