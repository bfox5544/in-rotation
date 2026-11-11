# 0017: Insights, a personal music profile on the Library page

Status: accepted (2026-11-03, owner request): "a Personal Analytics section within a second tab on the Library page… a personalized music profile rather than a generic analytics dashboard".

## What it shows
`GET /api/me/insights` (`backend/app/insights.py`) computes everything from the user's own rows (ratings, Listen Later and lists, dismissals, recommendation impressions) joined to the catalog. "Collected" albums are those rated or saved; an artist is the album's first credited artist.

| Section | From |
|---|---|
| Profile header: top-rated covers, a written summary, Albums Rated / Artists Explored / Average Rating / Genres Explored / Albums Saved | all of the below |
| Top genres | share of collected albums; each album counts toward its first 3 genres |
| Rating habits | half-star distribution and average |
| Favorite artists | highest average rating, with their best album's cover |
| Most collected | artists with the most rated or saved albums |
| Eras | albums per decade (with average rating) and per release year |
| Highest rated | the top-rated albums, as album cards |
| Recently discovered | latest albums rated or saved, and artists by when the user first met them |
| Recommendations | recommended, then rated, liked (4★ and up), saved and dismissed afterwards |

**The summary sentence** is written on the page from the numbers:
- top two genres, and the decade with the most albums
- "a generous rater" (average ≥ 4.2), "a tough critic" (≤ 3.2) or "a balanced rater"
- the browse popularity band (ADR 0015) of the median listener count of rated albums

## Recommendation statistics need new data
Nothing recorded which albums had been recommended to whom.

**New table:** `recommendation_impressions(user_id, album_id, source, shown_at)`, from migration 0006. It keeps the first showing only. It is filled from two places:
- For You and the home page's Picked for You, both `GET /api/me/recommendations` with source `for_you`. The popularity fallback isn't recorded, because it isn't personal.
- The Ask assistant's `recommend_albums`, with source `ask`.

**Counting rule:** a rating, save or dismissal counts only if it happened at or after the first showing. Albums rated before they were ever recommended don't inflate the numbers.

**Counting starts with this change:** earlier recommendations can't be reconstructed. The page says "Counting starts with your next visit" until something is recorded.

**Sign-in:** signing in moves an anonymous browser's impressions into the account, like the rest of the library.

## Charts
- **Single series, one hue:** every chart has one series, drawn in the existing amber on charcoal. Amber passes the contrast check against the page; the validator's lightness-band warning applies only to multi-hue palettes, which aren't used here.
- **Horizontal bars:** used for shares and counts, with the value at the bar's tip, 12 px thick, square at the baseline and rounded at the tip.
- **Columns:** used for distributions. They follow the dataviz guidance:
  - at most 24 px wide, rounded at the top, on one hairline baseline
  - only the tallest column labelled
  - every column shows its numbers on hover and keyboard focus
  - a "Show as Table" view for screen readers and exact values
- **Release years:** a thin strip of columns, one per year from the first to the last.
- **No new dependencies:** no chart library; it's plain HTML and CSS in `web/src/components/Insights.tsx`.

## Page
- **Tabs:** Library has two tabs, Collection (unchanged) and Insights. The tab is in the URL (`/library?tab=insights`), with arrow-key navigation between tabs.
- **Small libraries:** fewer than 3 rated or saved albums shows an invitation to choose albums instead of empty charts.

## Measured
A throwaway user on the full catalog rated 12 albums, saved 2 and opened For You. Their profile took 38 ms to compute.
- **Top genres:** alternative rock, art rock, dream pop.
- **Most collected:** Radiohead.
- **Main decade:** 1990s, as the summary reports.
- **Recommendation stats:** 12 recommended, 1 liked, 1 saved.

The page itself hasn't been opened in a browser.

## Revision: ratings only (2026-11-03, owner request)
The profile is now built from ratings only. Albums on Listen Later or a list no longer count toward genres, artists, eras, years or discoveries. The overview drops Albums Saved, and the API drops `albumsSaved`, `albumsCollected`, `lists` and `recentAlbums[].action`. "Most Collected" becomes "Most Rated" and "Recently Discovered" becomes "Recently Rated". Your own and public Insights are now the same profile. The private Recommendations section still counts recommended albums that were saved, since that measures what happened to a recommendation, not your taste.
