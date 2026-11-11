# 0008: Ratings feed the recommendation query (M8)

Status: accepted (2026-11-02). Favorites were later removed and ratings moved to half stars: see ADR 0009, which supersedes the favorites rules below.

## Data
- `user_ratings(user_id, album_id, rating 1-5, updated_at)`: Alembic migration 0002, with a CHECK constraint on the range.
- Ratings follow MusicBrainz merges like other saved rows (ADR 0007): they are stored under the current id, and a rating saved under an old id resolves to the current one. If two rows resolve to one album, the newer rating wins.
- On sign-in, an anonymous browser's ratings move into the account. Where both rated the same album, the account's rating wins.

## API
- `PUT /api/me/ratings/{album_id}` with `{"rating": 1-5}`, and `DELETE` to clear.
- `GET /api/me/library` gains `rated: [{album, rating}]`, newest first.

## How ratings shape recommendations (`recs/ratings.py`)
- **The query** is favorites plus rated albums. Each album's weight comes from its stars: **5★ 1.0, 4★ 0.8, 3★ 0.6**.
  - This "gentle" scheme beat uniform weights by about 2% NDCG@20 in a simulated experiment, and steeper schemes did worse (docs/experiments.md, run 2).
  - The served weights flow into `query_vector` (weights in model space), so the engine itself is unchanged.
- **A favorite with no rating counts as 5★.** An explicit rating always overrides the heart, so a favorite rated 2★ leaves the query.
- **1-2★ means "not for me".** The album is excluded from recommendations but is **not** a negative signal: the listening data has no dislikes to test negative weights against, so adding them would be an unmeasured guess.
- **Excluded from recommendations:** favorites, everything rated (any stars), listen later and custom lists.
- **Popularity fallback:** recommendations fall back to the most-listened albums when nothing has weight above 0 or nothing maps to the model.
- The For you page needs 3 albums that carry weight (favorites or ratings of 3★ and up).

## UI
- Five stars on the album page, as a radio group with labels ("Not for me" to "Loved it"). Choosing the current rating again clears it.
- The Library gains a "Rated" section grouped by stars.

## Not done
- Using 1-2★ as negative weights. This needs real usage data to evaluate.
- Ratings as a site-wide quality signal (for example, average stars on album pages). There are no users yet to average.
