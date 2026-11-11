# 0015: Catalog filters and sorting

Status: accepted (2026-11-03, owner request). Revised the same day (owner request): no separate Browse page; the filters open in a modal from the home page, Discover's genre chips are gone, and genre and subgenre are one searchable field.

The request was to filter the catalog by:
- genre and subgenre
- release year or decade
- artist
- popularity
- country of origin
- album type

and to sort it by newest, most popular and highest rated, "to explore music independently of the recommendation engine".

## Where the data comes from
Everything comes from MusicBrainz data the catalog already uses (ADR 0005), plus the listening data's listener counts. Nothing calls a live API.

| Filter | Source | Coverage (catalog of 389K albums) |
|---|---|---|
| Genre | Release group's genres, else its first artist's (unchanged) | as before |
| Subgenre | MusicBrainz genre relationships in the core dump (`genre`, `l_genre_genre`, `link`, `link_type`) | 1,782 parent links |
| Year, decade | `first-release-date` | 99% |
| Artist | `album_artists` (any credited artist) | all |
| Popularity | listeners in the listening data (`popularity`) | all |
| Country | the first credited artist's `country` in the release-group dump | 354K albums, 98% of listening |
| Album type | primary and secondary types | all |
| Highest rated | release group `rating` and `votes-count` (MusicBrainz community ratings) | 81K albums, 74% of listening |

- **Two new fields from the dump:** `ingest.musicbrainz` now keeps each release group's rating and votes, and each artist's country and type.
- **Four new core tables:** `ingest.catalog` reads `genre`, `l_genre_genre`, `link` and `link_type`. They are small, but they come out of the same 7.7 GB core archive, so the README extract command and `ingest.refresh --core` now include them.
- **Format bump:** the catalog moves to `schema_version` 4, and the API refuses older files.

## Decisions

### A genre includes its subgenres
- **What "subgenre" means:** MusicBrainz relates genres three ways: "subgenre" (black metal → atmospheric black metal), "fusion of" (ambient dub → ambient, dub) and "influenced by".
  - The first two put a genre inside another's family: filtering by "electronic" also finds trip hop and house albums.
  - "Influenced by" does not count (americana is influenced by blues, but isn't blues).
- **Storage:**
  - The edges are stored in `genre_parents`.
  - `genre_tree` holds the closure: every genre with all its ancestors, following parent chains up to 6 deep, which guards against cycles.
- **Filtering:** a filter is one indexed lookup through `genre_tree`.
- **Choosing a genre:** one searchable field covers genres and subgenres alike.
  - Typing searches every genre with albums. Each word must start a word of the name ("hop" finds hip hop and trip hop), and several words must appear together ("r&b" doesn't find blues rock).
  - An exact name comes first, then the rest by listeners. Each suggestion shows its family's album count and, for a subgenre, its most-listened parent ("in alternative rock").
  - Before anything is typed, the biggest genres are suggested.
  - `genres` gains `albums_all` and `listeners_all` for these counts. The existing `albums` and `listeners` columns (direct tags only) are unchanged.
- **Effect on the assistant:** its genre filter (ADR 0014) now uses the same families.

### Country means the artist's country
- **What it is:** MusicBrainz records where an **artist** is from. A release group has no country of its own; its releases have release countries, which mean where an edition came out, not origin.
- **Rule:** the first credited artist's country is used.
- **Limits:**
  - A few codes are areas rather than countries (XW Worldwide, XE Europe). The page names them.
  - Collaborations take the first artist's country.

### Highest rated: MusicBrainz community ratings, shrunk toward the mean
- **Why not site ratings:** In Rotation's own users' ratings would mean little with so few users.
- **What MusicBrainz ratings look like:** they are sparse and noisy. 65% of rated albums have a single vote, and the mean is about 3.95★.
- **The score:** `rating_score = (votes × rating + 10 × mean) / (votes + 10)`, a Bayesian average with a 10-vote prior. Unrated albums sort last.
- **Why 10 votes, not 3:** on the first build with a 3-vote prior, seven-vote 5★ fan ratings outranked The Dark Side of the Moon (4.75★ from 105 votes). With 10, well-established ratings lead.
- **On the page:** a note explains the source whenever this sort is chosen, and each card shows "★ 4.3 from 12 votes".

### Popularity bands, not a slider
These are listener bands in the listening data. The page shows each band's range, and the labels match For you's depth steps where they overlap (ADR 0012).

| Band | Listeners |
|---|---|
| Hits | 20,000+ |
| Popular | 5,000 to 20,000 |
| Less known | 1,000 to 5,000 |
| Under the radar | 200 to 1,000 |
| Deep cuts | under 200 |

### Album types
| Type | Rule |
|---|---|
| Studio albums | primary type Album, no secondary types |
| EPs | primary type EP |
| Singles | primary type Single |
| Live | secondary type Live |
| Compilations | secondary type Compilation |
| Soundtracks | secondary type Soundtrack |
| Remix albums | secondary type Remix |
| Mixtapes | secondary type Mixtape/Street |

A release group can match several of these, for example a live compilation.

### Sorting
- **Options:** most popular (the default without a keyword), newest, oldest, highest rated, and title A to Z.
- **With a keyword:** "Best match" is the default. It is the existing ranking: title matches, then artist matches, then by popularity.
- **Dates:** newest and oldest use the full first-release date, and undated albums go last. Newest starts with albums MusicBrainz lists as announced (dated after today); keeping them out would cost the index.

## API
- **`GET /api/albums`:** gains `year_from`, `year_to`, `artist` (artist id), `country` (two-letter code), `type`, `popularity` and `sort` alongside `q`, `genre`, `limit` and `offset`.
  - Unknown values for `type`, `popularity` or `sort` are a 422.
  - Genre names are matched loosely ("Hip-Hop" finds "hip hop").
  - Albums now carry `country`, `rating` and `ratingVotes`.
- **`GET /api/browse/options`:** returns decades, countries, types, popularity bands and sorts, each with album counts, plus how many albums are rated. It is computed once per catalog.
- **`GET /api/browse/genres?q=&limit=`:** returns genres and subgenres matching the typed words: `[{name, albums, parent}]`, about 5 ms.

## Page: the home page's "Browse albums" section
- **No separate page:** the filters live on the home page. A **Filters** button opens a modal dialog, and it reads "Filters (n)" when filters are on. Discover's genre chips are gone.
- **The modal** (native `<dialog>`: Esc and a backdrop click close it, and focus stays inside):
  - Genre (searchable) shows the choice as a removable pill.
  - Decade with an exact-year box (a year replaces the decade), Popularity, Country (the artist's) and Album Type.
  - Artist and sort were taken out of the modal (owner request, 2026-11-03). The API still accepts `artist` and `sort`; the page always lists by popularity.
  - Changes are a draft until the main button, which shows how many albums the draft matches ("Show 1,234 albums"). "Clear all" empties the draft, and closing discards it.
  - On phones the modal fills the screen.
- **URL state:** filters and sort live in the home page URL (`/?genre=trip+hop&country=GB`), so Back works and a filtered view can be shared.
- **Results:** 48 at a time, with "Show More". With filters on, cards show the year. "Clear Filters" returns to the most-listened albums.
- **Search page:** unchanged. A keyword search stays on the header search box.

## Measured (full catalog, 31 October dump, warm cache)
**Speed:**
- Any filter combination, rock (140K albums) included: a page takes 40–100 ms, of which about 70 ms is the total count.
- Browse options: 0.6 s on first use, then cached.
- The first queries after a catalog swap can take seconds while the 1 GB file loads into the OS cache.

**What it took:**
- **Genre filter:** the first version joined `genre_tree` to `album_genres` per query, and paging rock took 0.5 s. A correlated version over the same tables took 37 s, because it looped over rock's hundreds of subgenres for every album.
- **Membership table:** `album_family` (genre family → album rowid, 1.15M rows, WITHOUT ROWID) turns the check into one key lookup.
- **Two query forms:** families of 20,000+ albums walk albums in sort order and stop after a page. Smaller ones collect their albums first. A test checks that both forms give identical results.
- **Sort indexes:** each sort has an index whose columns match its ORDER BY exactly (`app.catalog.SORTS` and the `SCHEMA` comment). The catalog grew from 893 MB to 1.0 GB.
- **Rowids:** `album_family` refers to albums by rowid, which VACUUM may renumber, so the builder fills it after the final VACUUM.

**The rebuild:**
- The local `release-group.tar.xz` was the 28 October dump, older than the 31 October one the live catalog came from.
- A plain `ingest.catalog` run would have rolled the catalog back and changed 105 album ids (ties resolved differently in newer data).
- The rebuild went through `ingest.refresh` instead. It fetched the 31 October dump again: same 389,550 albums, no retired ids, unchanged coverage. A final `ingest.catalog` rebuild from that same Parquet added the 10-vote prior and `album_family`, again with 0 album changes.

## Limits
- **Popularity is listener-based:** it reflects the listening data's users (mostly Last.fm-era listening), not today's charts.
- **Country is per artist:** it isn't per album, and about 9% of albums have no artist country.
- **Ratings cover about a fifth of albums:** they skew toward what MusicBrainz editors care about.
- **Genre tags are limited:** genres stay the top 5 tags per release group, and the subgenre tree is only as complete as MusicBrainz's genre relationships.
