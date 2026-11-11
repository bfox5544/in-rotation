# 0003: Preprocessing and preference weights (M3)

Status: accepted. Parameters are provisional until M4 evaluates them.

## Album identity
An album is the normalized key `artist | title` (accents removed, lowercased, punctuation collapsed, Unicode letters kept). Edition suffixes are stripped from the title first. "Live", "Remix", "Mono/Stereo" and "Taylor's Version" are not stripped because they are different recordings; "- Single", "EP" and soundtrack suffixes are not stripped because they are different releases.

Edition tags are deluxe, remaster(ed), expanded, anniversary, bonus, collector('s), limited, reissue, explicit, clean, edition, disc/disk/CD numbers, and "<special|standard|international|U.S.|UK|PA|LatAm|extended|dirty|double disc> version". Rules, in order (`STRIP_STEPS` in `recs/preprocess.py`):
1. " - ", " – ", " — ", " ~ " and ": " are one separator.
2. Bracketed text containing a tag is removed. A trailing unclosed bracket (Last.fm truncation, "Born To Die (The Paradise Edit") is removed whatever it contains.
3. A trailing separated segment containing a tag is removed, twice ("In Utero - 20th Anniversary - Deluxe Edition"). "SOS Deluxe: LANA" loses everything from "Deluxe".
4. Bare suffixes are removed only with unambiguous wording: "<deluxe|special|limited (tour)|collector's|platinum|expanded|Nth anniversary> edition/version", "Nth anniversary", "disc 1"/"CD1". A bare trailing "Deluxe" is kept because "Hellbilly Deluxe", "Love Deluxe" and "Cupid Deluxe" are real titles.
5. Data-driven fold: a normalized title still ending in "deluxe" or "<up to 2 words> edition" joins the same artist's shorter key when that key has at least 10 listeners and 10% of the variant's ("Validation Deluxe", "Born To Die Paradise Edition"). The threshold stops "Hellbilly Deluxe" (1,945 listeners) folding into a truncated 2-listener "Hellbilly".

On the real dataset (2026-10-30), the October rules left 3,093 kept keys with edition words, and Born to Die alone was split across several keys. The widened rules removed 33,068 album keys, folded 711 by rule 5, and merged 53K more within-user duplicates. Rule 5 depends on the data, so M5 matching code must apply the string rules and then look up the folded key in `albums.parquet`, not recompute the fold.

Not handled: truncated titles without a bracket ("Whatever People Say I Am, That" for the Arctic Monkeys album) and spelling variants such as "The Beatles (White Album)" vs "(The White Album)". A prefix merge would also wrongly join "The Fame" and "The Fame Monster", so those wait for the M4 fuzzy-matching measurement.

The MusicBrainz ID is stored as an attribute (most common per album), not as the identity. Reason: the sample IDs may be per release, so editions of one album would otherwise split into several model columns. `report.md` shows how many album keys carry several IDs, which tells us whether that happens. `python -m recs.probe_mbids` samples IDs against MusicBrainz to learn their type.

Known gaps: "The Weeknd" vs "Weeknd", feat. credits in artist names, and translated titles are different keys. M4 can measure whether a fuzzy pass is worth it.

## Cleaning rules
Rows are dropped for: missing user, missing album or artist, rank outside 1-50, playcount not above 0, or a name that is empty after normalizing. Each dropped row is counted once under its first failing rule. A user listing the same album twice (including via merged editions) becomes one row with the best rank and summed plays.

## Filters
Albums with fewer than 2 listeners are removed (they cannot connect two users), then users with fewer than 5 remaining albums. This is one pass, so a few albums can end slightly under the threshold. Both numbers are flags on `recs.preprocess`.

## Weights
`w = alpha * rank_score + (1 - alpha) * play_score`, always in (0, 1]. Rank scores use absolute rank (not the user's list length) so rank 1 means the same everywhere: linear `1-(r-1)/50`, log `1/log2(r+1)`, or exponential. Play score is `log1p(plays)` divided by that user's maximum. Defaults: linear, alpha 0.5. Weights are computed when the matrix is built, not stored in the Parquet files, so M4 can sweep them without re-running DuckDB.

## Storage
`interactions.parquet`, `albums.parquet`, `user_album.npz` (CSR float32, about 8 MB per million interactions) and the report live under `data/model/` (git-ignored). Popular albums get low `album_idx`.
