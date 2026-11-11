# 0028: Item kNN replaces user kNN

Status: accepted (2026-11-10, owner decision: "Switch to item kNN. Ensure all necessary changes across all pages are made to represent this.")

## Why
The model comparison (docs/experiments.md run 6) put six recommender families through the M4 protocol on one split. Each family was tuned on 5,000 listeners and tested once on another 5,000. Item-based kNN beat the served user kNN by **+0.0190 ± 0.0028 NDCG@20 (+7.9%)** on full queries and by **+0.0041 ± 0.0023 (+3.0%)** on 10-album queries. It also recommended more distinct albums (23,368 against 20,161) with the same head share (75%). ALS was ahead only on full queries, with 97% head share and a 12-minute fit.

## The model (`recs/item_knn.py`)
- **The same weight matrix as before** (linear rank and plays, α 0.5). An album is its column, scaled to length 1.
- **Scoring:** `score(b) = Σ q(a) · cos(a, b)` over the rated albums a, computed as `(q Cᵀ) C`, two sparse products through the listeners. No album × album matrix is stored, which would be 633K².
- **No popularity adjustment.** The cosine already divides by album size, and β 0.1 cost 0.015 NDCG@20 (run 6).
- **The query is unchanged:** ratings of 3★ and up, weighted 1.0 down to 0.6 (ADR 0008, 0009).
- **Re-ranking is unchanged:** exclusions, the artist cap of 2, and edition merging.
- **Memory and speed:**
  - The model holds C and Cᵀ (about 400 MB), and the API builds it in about 4 s at startup.
  - A first For You page takes 120-250 ms on the full data. Later pages take about 50 ms, because each taste's scores are cached (`SCORE_CACHE`, 32 queries). User kNN took about 30-55 ms a page.
- **`recs.recommender.Recommender` (user kNN) stays** for the evaluation history in runs 1-5 and the comparison. It no longer serves.

## What changed with it
| Feature | Before (user kNN) | Now (item kNN) |
|---|---|---|
| For You, Picked for You, `/me/map`, Ask's `recommend_albums` | Weighted sum over the 100 nearest listeners, ÷ listeners^0.25 | Summed similarity to the rated albums |
| Listeners Also Love (album pages), related artists | The album as a one-album query | Same: now simply the most similar albums |
| How Well Known (ADR 0012) | Caps, the 10-listener floor, β 0 under a cap | Caps and the floor kept, checked again in run 7: Under the Radar finds 0.240 of loved smaller albums against 0.104 uncapped |
| Filters (ADR 0026) | Ranked by 1,000 neighbours, filled from 5,000 (`FILTER_K`) | Every album has a score, so a filter only narrows the ranking. `FILTER_K` is gone |
| Because You Rated (ADR 0021) | Seeds whose fans among the neighbours have the pick, by share | The seeds that carry at least 15% of the pick's score (`TELLING_SHARE`), ranked by how much closer the pick is to them than the rest of the page is. Raw shares named a central album, such as Kid A, on most cards |
| Match score (ADR 0019) | Percentile among albums 2+ of the 300 nearest listeners have | Percentile among albums held by at least 0.1% of the listeners who have one of your albums, and at least 3 of them (`MATCH_SHARE`, run 7). API field `neighbours` became `listeners` |
| Ask's "why" | "N of the 100 listeners most like this query have it" | Listeners who have a query album and also have it, plus the query albums' shares of the score. The prompt says "most similar to" |

## Settings checked again (run 7)
| Setting | Result on item kNN | Kept? |
|---|---|---|
| Weights, α 0.5 | Within 0.003 of the best at both query sizes (α 1 best on full, α 0 at 10 albums) | Kept |
| Star weights, gentle | Best at both sizes (0.2633 against 0.2569 uniform on full queries) | Kept |
| How Well Known caps and floor | Cap and floor best at every cap and both query sizes | Kept |
| Match score support | 0.1% of holders: 76% of loved albums scored, median 98 (10 albums), lift above 200× | New |
| Thinly held albums | With 3 rated albums 21% of picks had under 10 listeners and many had no match score. Leaving out albums under 10 listeners or without the match support: NDCG@20 0.085 → 0.092 (3 albums), 0.141 → 0.147 (10) | New: `SUPPORTED_ONLY`, `FLOOR` 10 |

## Pages updated
- **How Recommendations Work, Overview:** the lead, steps 3-5, Match Scores and How Well It Works now describe albums like yours. How Each Setting Was Chosen has six charts:
  1. Which way of recommending
  2. Rank and plays
  3. Star weights
  4. The popularity adjustment
  5. How Well Known
  6. The match score's reference set

  The user kNN charts (neighbourhood size, adding up, filter neighbourhoods) are gone.
- **Technical Details:** item kNN is marked as served, The Served Model shows the item formulas, and the experiments table adds runs 6 and 7.
- **Album pages:** the match card's sentence ("Most like X and Y of the albums you rated. N of the M listeners who have your albums also have it.") and How Match Works.
- **Home:** the hero and the ratings-progress line.
- **Data Sources:** the example count.
- **For You:** a code comment only, because "Because you rated" reads the same.

## Limits
- Run 7 used 2,000 listeners, one split, and simulated stars for the star check, as in run 2.
- The match score's reference set grows with popular seeds. Loved albums cluster at 95-100 more than they did under user kNN (median 98 against 92).
- Within-list diversity (artists and genres per list) was not measured for either model.

## Revision (2026-11-10): support relative to the album's size
The owner reported that the Deep Cuts page wasn't full. 0.1% of the listeners who have your albums is 65-130 people for an ordinary taste, more than most albums under 200 listeners have in all. An album now counts as supported when that many have it, **or 5% of its own listeners if that is fewer** (never under 3, `OWN_SHARE`, `Engine._need`). The rule applies both to For You picks and to the match score's "can it be scored" test, so every pick still gets a score. The percentile's reference set is unchanged. Run 9: at Deep Cuts with 10 rated albums, lists that couldn't fill fell from 29% to 1%, and smaller albums found rose from 0.151 to 0.181. At Anything it's the same or slightly better (full queries 0.2643 → 0.2673 NDCG@20).
