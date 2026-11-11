# 0019: Match score on album pages

Status: accepted (2026-11-03). The owner asked "could there be a similarity score out of 100?", agreed to the proposal, and asked for it on the album page.

## What it shows
- **The score:** a "92 Match" block on every album page, with a short amber meter.
- **Why:** a line built from the data behind it, like "43 of your 300 closest listeners have it, alongside OK Computer and Kid A".
- **How Match Works:** a disclosure saying it ranks the album among everything listeners like you have and is not a star prediction.

## How it is computed (`recs/match.py`, `Engine.match`)
1. **The query.** The query is the For You one: ratings of 3 stars and up, weighted by stars (ADR 0008). **The album itself is left out**, so an album you rated is scored as if you hadn't, and the page says so.
2. **Your closest listeners.** These are the 300 nearest historical listeners. Listeners with zero similarity are dropped.
3. **Scoring.** Each album is scored by the engine's weighted sum, **without the popularity dampener**.
4. **The reference set.** It holds every album at least 2 of those listeners have, that the site can show, and that isn't in the query.
5. **The score** is the album's midrank percentile in that set, from 0 to 100.

Statuses:
| Status | Meaning |
|---|---|
| `ok` | a score |
| `few_listeners` | under 2 of your closest listeners have the album. The page says how many |
| `not_in_data` | no model album maps to it |
| `no_taste` | no ratings of 3 stars or more. The page links to onboarding |

**Why a percentile.** Raw engine scores depend on the query, so the same number means different things for different users. A percentile keeps 90 meaning the same for everyone.

**Validation.** Run 4 in `docs/experiments.md`, on 2,000 held-out historical users:
- **Settings:** 300 neighbours with a support of 2, and the dampener off, were chosen there.
- **Loved albums score high:** albums people really love get a median score of 92 (with 10-album queries).
- **High scores are meaningful:** a 95-100 album is 36 times likelier to be loved than one under 50.
- **Coverage:** about a third of loved albums get no score (too few closest listeners have them).

## API
`GET /api/albums/{id}/match` (session needed) returns `{status, score, neighbours, withAlbum, alongside: [Album]}`. `alongside` is up to 2 of your liked albums that the same listeners most often have. 404 for an unknown album.

## Cost
- The neighbour search and scoring take about 20 ms on the full data.
- Each later album page with the same taste takes about 3 ms: the last 64 taste queries are cached in memory (about 4 MB each), keyed by the query.
- The page refetches when your liked ratings change.

## Known limits
- Historical users only ever appear as counts.
- It measures how common the album is among listeners like you, not quality or novelty. A hit your neighbours all have scores high even if you already know it.
- Albums outside the listening data (new releases among them) get no score.
- Album cards (For You, search) don't show it yet. That would need the same cache per card, and is the obvious next step if the score reads well.

## Revision (2026-11-10): item kNN (ADR 0028)
With item kNN, the score is the percentile of an album's summed similarity to the rated albums. It's measured among the albums held by at least 0.1% of the listeners who have one of the user's albums, and by at least 3 of them (`engine.MATCH_SHARE`, `MATCH_MIN_SUPPORT`). Run 7 tried 0.1%, 0.3%, 1% and 3%. 0.1% scored the most loved albums (76% with 10 albums, against 65% before) and separated best (lift above 200×), though loved albums now cluster higher (median 98 against 92). `alongside` is the two rated albums carrying most of the score. The API field `neighbours` became `listeners`. The 300-neighbour settings above describe the user kNN version.

## Revision (2026-11-10): no listener counts on the card
At the owner's request, the match card no longer says how many of the listeners who have your albums also have this one. It keeps the score, the meter and "Most like X and Y of the albums you rated". An album without a score says "Too few people who share your taste have this album to score it." The API still returns `listeners` and `withAlbum`, and Ask's `why` tool still uses them.
