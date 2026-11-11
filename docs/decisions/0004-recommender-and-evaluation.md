# 0004: Recommender structure and evaluation protocol (M4)

Status: accepted. Chosen parameters (2026-10-30, now the `RecommenderConfig()` defaults): linear rank weights, alpha 0.5, plain cosine, K 100, weighted sum, popularity dampener beta 0.25. Evidence: `docs/experiments.md`.

## Structure
`recs/recommender.py` composes three swappable parts, each picked by name in `RecommenderConfig`, so an experiment is a config change:

| Part | Implementations | Role |
|---|---|---|
| `WeightFn` | `RankPlayWeights` (ADR 0003) | interactions to preference weights |
| `SimilarityFn` | `CosineSimilarity(asymmetry)` | query rows against all historical users |
| `Aggregator` | `WeightedSum`, `NormalizedSum(shrink)` | the top-K neighbours' weights to album scores |

A popularity dampener (`score / listeners^pop_beta`) applies after aggregation. `PopularityRecommender` is the baseline and has the same `recommend_batch` interface.

- **No all-pairs similarity.** A batch of queries (64 by default) is one sparse product against the transposed user x album matrix. The result is a dense batch x users block (about 120 MB at 476K users), and only the top K users are kept (`np.argpartition`). On the real data this takes about 4 ms per query, and scoring takes about 2 ms.
- **Asymmetric cosine** `q.r / (|q|^(2a) |r|^(2(1-a)))` generalizes cosine (a = 0.5). Raising `a` stops users with long or heavy lists being penalized as much, so neighbours are chosen more by overlap.
- **Exclusion** happens inside `recommend_batch`. Albums in the query are always excluded unless `exclude_query=False` (the rediscovery flag), and callers can pass further exclusions (rated or listed albums). Albums with no positive score are never returned, so a list can come back short; M5 should over-fetch (about 3x) to absorb albums that don't map to the catalog.
- `Recommender.reconfigure()` copies a fitted model with different scoring settings (K, aggregator, shrink, beta) without refitting, which is what makes the sweep affordable.

## New-user queries
`recs/query.py` turns picks into a sparse row over model album indexes. Each pick has weight 1.0, or a caller-supplied weight in M8. Indexes outside the model, and weights of 0 or less, are dropped with a log line, never an error. `AlbumLookup` resolves an album key or MBID to a model index; M5's `album_id_map` builds on it. An empty query returns an empty list, and the API should then fall back to popularity.

## Evaluation protocol
- **Sample:** historical users with at least 10 albums; 5,000 for tuning (seed 0) and a **disjoint** 5,000 for the final report (seed 1). The sweep picks the best settings on the tuning sample, and the reported numbers come from users it never saw.
- **Leave-k-out:** a random 20% of each user's albums (at least one) are hidden. The query is the other 80% with **weight 1.0 each**, which matches a site user's picks; the user's own rank and play count are not used in the query.
- **No leakage:** evaluation users are removed from the training matrix, so a query cannot find its own full row as a neighbour.
- **Metrics at K = 10 and 20 (binary relevance):** precision, recall (hits / hidden), NDCG, hit rate. **Bias metrics:** the number of distinct albums recommended across all users, catalog coverage, the mean listener count of recommended albums, and the share of recommendations from the 1% most-listened albums ("head share").
- **Target:** NDCG@20. Bias metrics are reported next to it and inform the choice, but are not optimized automatically.
- **Sweep, staged** (`recs.evaluate.sweep`):
  1. K {50, 100, 200, 500} x aggregator {sum, normalized with shrink 0.1, 1, 10} x beta {0, 0.25, 0.5}, using default weights and plain cosine.
  2. rank function {linear, log, exp} x alpha {0, 0.5, 1}, rescoring K, aggregator and beta near the stage-1 best.
  3. asymmetry {0.5, 0.75, 0.9}.

  A full grid would be about 1,300 settings. The stages assume the parameter groups interact weakly; stage 2 rescoring K and beta is a partial check of that.

## Known limits of this protocol
- Hidden albums come from users' top-50 lists. Albums outside those lists are unknown, not disliked, so precision is a lower bound.
- A random holdout ignores time: the dataset has no timestamps, so the evaluation cannot measure predicting future listening.
- Popular albums are easier to hit, so accuracy alone rewards popularity bias. That is why head share and distinct albums are reported next to accuracy.
- Hidden albums that only the evaluation users had are absent from training and can't be recommended by any model. This caps every model equally.

## Revision (2026-11-10): item kNN (ADR 0028)
The evaluation protocol stands, but user kNN no longer serves. Item kNN (`recs/item_knn.py`) beat it by 7.9% NDCG@20 on this protocol (docs/experiments.md run 6) and replaced it. `Recommender` stays for the evaluation history.
