# 0009: Ratings replace favorites; half stars

Status: accepted (2026-11-02). The owner asked to remove favorites, allow only star ratings, and allow half stars. Supersedes the favorites parts of ADR 0002, 0006 and 0008.

## What changed
- **Favorites are gone** from the data, the API (`/api/me/favorites` returns 404), the UI (the heart chip and the "Add to favorites" button) and the recommendation query. **A star rating is the only taste signal.**
  - Listen later and custom lists are unchanged; they are "to hear" and "collections", not taste.
- **Ratings run from 0.5 to 5 in half stars.** The API takes and returns a number (`{"rating": 3.5}`). Anything that isn't a multiple of 0.5 in that range is a 422.
- **Storage is `user_ratings.half_stars`, a whole number from 1 to 10**, so comparisons and grouping stay exact. There is no floating point in the database.

## Migration 0003 (data)
- **Existing ratings are doubled** (4★ → 8 half stars).
- **Each favorite the user had not rated becomes a 5★ rating.** That is how ADR 0008 already weighed an unrated favorite, so no one's recommendations change.
- **A favorite the user had also rated keeps that rating.** The explicit rating already won under ADR 0008.
- The favorites table is dropped.
- The ratings table is rebuilt rather than altered, so the same steps run on PostgreSQL and on SQLite (tests).
- **Downgrading is lossy:** half stars round down, and favorites come back empty.
- On the dev database, 90 favorites and 6 ratings became 96 ratings. The test `test_migrations.py` checks the conversion on both database engines.

## Recommendation weights
- The weights chosen in M8 (3★ 0.6, 4★ 0.8, 5★ 1.0) lie on a straight line, so half stars sit on it: **3.5★ 0.7, 4.5★ 0.9**.
  - This is interpolation, not a new experiment: the M8 experiment simulated whole stars only.
- **Below 3★, including 2.5★, an album only stays out of recommendations**, as in ADR 0008.

## UI
- **The rating control is one slider** (`role="slider"`), not ten radio buttons.
  - Mouse or touch: the left or right half of a star picks the half or whole value, and choosing the current value again clears it.
  - Keyboard: arrows step half a star, Home/End go to 0.5/5, keys 1-5 jump to whole stars, and Delete clears.
  - Screen readers hear "3.5 stars, Liked it".
- **Rated albums show a small "★ 4½" badge** on their cover everywhere.
- **The Library opens with "Your ratings"**, grouped from highest to lowest.
- **Onboarding (`/start`) is rating:** each album has compact stars, and continuing needs 5 albums rated 3★ or more.
- The For you page needs 3 albums rated 3★ or more.
