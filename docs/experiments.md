# Experiments

How the recommender was tuned and how well it works. Protocol: ADR 0004. Raw output of the latest run: `data/experiments/` (git-ignored); rerun with `python -m recs.evaluate --model-dir data/model --users 5000`.

## Run 1: 2026-10-30, M4 baseline sweep

**Data:** `data/model` after the widened edition rules (476,304 users, 633,053 albums, 22.5M interactions).
**Setup:** 5,000 tuning users (seed 0), and 5,000 *different* test users (seed 1). Each user has a random 20% of their albums hidden and is queried with the rest at weight 1.0. The sweep covered 80 CF settings in three stages and took 21 minutes on 12 cores.

### Headline (test users, never seen by the sweep)

| model | NDCG@10 | NDCG@20 | P@10 | R@20 | hit rate@20 | distinct albums@20 | mean listeners of recs | head share@20 |
|---|---|---|---|---|---|---|---|---|
| popularity baseline | 0.019 | 0.026 | 0.017 | 0.030 | 0.22 | 35 | 31,193 | 1.00 |
| CF defaults (K 200, sum, beta 0) | 0.196 | 0.227 | 0.149 | 0.211 | 0.79 | 9,608 | 11,098 | 0.91 |
| CF sweep winner | 0.209 | 0.242 | 0.163 | 0.229 | 0.83 | 19,051 | 7,100 | 0.78 |

The "head" is the 1% most-listened albums (6,331). Head share is the fraction of recommendations taken from it.

- **CF is about 9x the popularity baseline** on NDCG@20. For 83% of users, at least one hidden album appears in the top 20.
- **The sweep winner beats the defaults** on accuracy (+0.015 NDCG@20). It also recommends twice as many distinct albums and draws less from the head (78% vs 91%).

### What mattered (95% intervals from a paired per-user comparison on the test users)

| change | NDCG@20 effect | verdict |
|---|---|---|
| K 200 to 100, plus popularity dampener beta 0.25 | **+0.0140 ± 0.0023** vs defaults | real; the main gain |
| then alpha 0.5 to 0 (plays only) and asymmetry 0.5 to 0.9 | +0.0012 ± 0.0013 | **noise** |

Stage by stage, on the tuning users:
- **Popularity dampener:** beta 0.25 is the sweet spot. Accuracy stays the same or rises (0.2383 vs 0.2375 at K 50), distinct albums go from about 19K to about 71K across K values, and head share drops from 0.95 to 0.84. At beta 0.5 accuracy falls sharply (0.21 at best, 0.14 at K 100). Too much of the long tail is noise.
- **Neighbours K:** 50 to 200 are within about 0.002 of each other at beta 0.25, and 500 is clearly worse (0.229). Fewer neighbours also give more varied lists.
- **Aggregator:** the plain weighted sum is as good as normalized with shrink 1 or 10 and much better than shrink 0.1 (0.17). Shrink 0.1 lets an album held by a single neighbour score near the top. Normalizing gains nothing here, so the simpler sum stays.
- **Weights:**
  - The linear rank score plus play blend (alpha 0.5) scores 0.2383, and plays only (alpha 0) scores 0.2397, which is within noise.
  - Rank only (alpha 1) is slightly worse with linear (0.2368) and clearly worse with log or exp (0.226 and 0.223). Steep rank curves throw away too much of a top-50 list.
  - A user's listening history therefore carries real signal beyond list position, but the blend loses nothing.
- **Asymmetric cosine:** 0.5, 0.75 and 0.9 are within 0.0014. No effect.

### Short queries: what site users actually send
Site users pick 3-10 albums during onboarding, while the sweep queried with about 38. This run used the same 5,000 test users and the same hidden albums, but kept only a random 3, 5 or 10 of each user's remaining albums as the query (`EvalConfig(max_query=...)`). Raw rows: `data/experiments/short_queries.csv`.

| picks | popularity NDCG@20 | CF K 100, beta 0 | CF K 100, beta 0.25 | hit rate@20 (beta 0 / 0.25) | distinct albums (beta 0 / 0.25) | head share (beta 0 / 0.25) |
|---|---|---|---|---|---|---|
| 3 | 0.023 | **0.101** | 0.094 | 0.59 / 0.55 | 14.5K / 29.7K | 0.86 / 0.65 |
| 5 | 0.023 | **0.115** | 0.111 | 0.65 / 0.63 | 13.0K / 25.6K | 0.89 / 0.71 |
| 10 | 0.024 | 0.137 | 0.136 | 0.70 / 0.70 | 11.7K / 21.9K | 0.90 / 0.75 |
| all (about 38) | 0.026 | 0.234 | **0.240** | 0.81 / 0.82 | 11.4K / 20.2K | 0.89 / 0.75 |

- **CF still beats popularity by 4-6x even with 3 picks.** Accuracy roughly halves compared with full queries, as expected.
- **beta 0.25 costs accuracy on short queries** (about -7% NDCG at 3 picks, about 0 at 10). In exchange it doubles the number of distinct albums and cuts head share by about 20 points. On long queries it is a pure gain. So beta is a **product trade-off for onboarding-sized queries**, not a free win.
- **K 50-200 are within about 0.003** at every query size. K 500 is consistently the worst.

### Decision (2026-10-30)
**Owner chose beta 0.25.** The settings are linear weights, alpha 0.5, plain cosine, K 100, weighted sum, beta 0.25, and they are now the `RecommenderConfig()` defaults. Before this decision the defaults were K 200 and beta 0: "CF defaults" in the tables above and in Run 1's `final.csv` means those old settings.

Options that were considered:
- **beta 0.25 (chosen):** about 7% lower NDCG at 3 picks, but twice the number of different albums and far fewer chart hits. It is also the most accurate setting once a user has about 10 or more albums.
- **beta 0:** the most accurate for brand-new users, but leans heavily on the head (86-90% of recommendations).
- A middle path is to scale beta with query size (0 below 5 picks, 0.25 from 10). It's cheap to add but not yet evaluated.

Plays only (alpha 0) and asymmetric cosine tied with these settings, so the simpler options stay. They keep rank in the weights, which M8's rating-scaled queries build on. `data/experiments/chosen_config.json` holds the sweep's automatic winner; this recommendation deliberately overrides it, and the M5 ADR records these settings as the ones served.

### Sample lists (recommended settings, top 10)
- **Grimes *Visions*, Burial *Untrue*, FKA twigs *LP1*, James Blake:**
  - James Blake *Overgrown*, Burial *Burial*, The xx *Coexist* and *xx*, SBTRKT, Arca *Xen*, Purity Ring *Shrines*, Jamie xx *In Colour*, Grimes *Halfaxa*, Crystal Castles.
  - With beta 0, Frank Ocean, Lana Del Rey and Radiohead were in this list.
- **Raekwon, *Illmatic*, *The Infamous*, *Liquid Swords*:**
  - Mobb Deep *Hell on Earth*, *36 Chambers*, *It Was Written*, *Liquid Swords*, Big L, Ghostface *Ironman* and *Supreme Clientele*, Gang Starr, *Reasonable Doubt*, *Ready to Die*.
  - *Liquid Swords* was in the query, but it still appears because it reaches the model under a different key (GZA vs "GZA/Genius"). That is an artist-alias gap.
- **Pop (*BRAT*, Chappell Roan, *E•MO•TION*):** 7 of 10 are Carly Rae Jepsen or Charli XCX albums.
- **Metal (*Master of Puppets*, *Reign in Blood*, *Rust in Peace*):** all 10 are by the query's artists or Pantera.

### Findings to act on
1. **Same-artist concentration.** The metrics reward recommending the rest of a known artist's catalogue, since those albums are often among the hidden ones, so accuracy pushes toward it. That's fine for some users but dull for discovery. **M5:** add a per-artist cap in re-ranking (for example at most 2 per artist in the top 10), and measure what it costs in NDCG here.
2. **Artist aliases split albums** ("GZA" vs "GZA/Genius", like "The Weeknd" vs "Weeknd"). Queried albums then come back as recommendations. M5 mapping should also exclude albums whose normalized title matches a query album by the same artist alias.
3. **Popularity bias is reduced, not gone:** even with the dampener, 75-78% of recommendations come from the top 1% of albums.

### Limits
- One random holdout split per sample, with no time ordering (the dataset has none).
- Hidden albums come from top-50 lists, so precision is a lower bound.
- Tuning and test samples come from the same population of heavy Last.fm users. Site users may have different tastes; that only becomes measurable from real usage after M5.
- The sweep tuned on full queries. Short-query results come from a smaller grid (K x beta) on the test users only, so treat them as a check rather than a tuned optimum.

## Run 2: 2026-11-02, M8 rating weights
`python -m recs.ratings --users 5000` (seeds 7, 8, 9; about 25 minutes). Raw output: `data/experiments/rating_weights.csv` and `rating_weights_summary.csv`.

**Question:** when a site user's query albums carry star ratings, should higher-rated albums weigh more, and by how much?

**Setup:** the dataset has no ratings, so each held-out user's top-50 ranks stand in for them: rank 1-10 is a 5, 11-25 a 4, 26-50 a 3.
- Recommendations use the served settings (ADR 0004) and the M4 leave-out protocol, with the user's remaining albums as the query, or 10 random ones.
- Each weighting scheme is compared with uniform weights on the same users. The numbers are mean NDCG@20 differences ± their standard deviation over the three seeds.

| Scheme (5★ / 4★ / 3★) | NDCG@20, all picks | vs uniform | NDCG@20, 10 picks | vs uniform |
|---|---|---|---|---|
| uniform (1 / 1 / 1) | 0.2354 | | 0.1360 | |
| **gentle (1 / 0.8 / 0.6)** | **0.2398** | **+0.0044 ± 0.0009** | **0.1392** | **+0.0032 ± 0.0012** |
| linear (1 / 0.67 / 0.33) | 0.2393 | +0.0039 ± 0.0010 | 0.1383 | +0.0024 ± 0.0013 |
| steep (1 / 0.4 / 0.15) | 0.2334 | -0.0020 ± 0.0020 | 0.1322 | -0.0038 ± 0.0016 |

### Findings
- **Grading helps a little, and only gently.** Gentle weights add about 2% NDCG, consistently across seeds and query sizes.
- **Steep weights hurt.** They make a 3★ album nearly irrelevant, which throws away real taste signal; a 3★ album is still an album the user chose.
- **Stronger grading also lowers popularity bias** (mean popularity of recommended albums 6,700 → 6,500 → 6,100). That is a side effect, not a reason to choose a scheme.

### Decision (2026-11-02): gentle
- **Served weights** (`recs.ratings.RATING_WEIGHTS`): 5★ 1.0, 4★ 0.8, 3★ 0.6.
- **A favorite with no rating counts as 5★.** (Favorites were removed later; half stars sit on the same line, 3.5★ 0.7 and 4.5★ 0.9: ADR 0009.)
- **1-2★ albums stay out of the query and out of recommendations.**

### Limits
- Simulated ratings follow rank buckets. Real users rate less consistently, which should only shrink the difference between schemes.
- **Negative feedback is untested.** The data has no dislikes, so 1-2★ albums are not used to push similar albums down. That would need real usage data.

## Run 3: 2026-11-02, less popular recommendations (For you depth)
`python -m recs.less_popular --users 2000` (seed 11; about 5 minutes). Raw output: `data/experiments/less_popular.csv`.

**Question:** how should the "How well known?" slider find less popular albums a user will still like?

**Setup:**
- M4 leave-out protocol and served settings, with the user's remaining albums as the query, or 10 of them.
- For each listener cap, only the hidden albums at or under the cap count. These are the less known albums the user turned out to love. The scores are recall@20 and hit rate (any of them in the top 20).
- Listeners are training-matrix listeners, out of about 476K.

| Cap | Uncapped, served ranking | Dampener 0.5 | Dampener 1.0 | Cap | Cap, no dampener | **Cap, no dampener, 10+ listeners** |
|---|---|---|---|---|---|---|
| 5,000 (all / 10 picks) | 0.155 / 0.100 | 0.116 / 0.063 | 0.006 / 0.004 | 0.198 / 0.139 | 0.195 / 0.139 | **0.195 / 0.139** |
| 1,000 | 0.096 / 0.061 | 0.088 / 0.049 | 0.008 / 0.005 | 0.152 / 0.100 | 0.161 / 0.109 | **0.160 / 0.108** |
| 200 | 0.054 / 0.034 | 0.062 / 0.036 | 0.012 / 0.007 | 0.103 / 0.069 | 0.119 / 0.079 | **0.115 / 0.077** |

Recall@20 of hidden albums under the cap. Median listeners of the suggestions, with all picks: served ranking 2,720; dampener 0.5, 6; dampener 1.0, 2; the chosen method 1,975, 507 and 102 at the three caps.

### Findings
- **A stronger dampener is the wrong tool.** It drifts to albums with 2-6 listeners that one neighbour happens to own, and it finds fewer of the albums users loved than the uncapped ranking.
- **A cap works.** It finds 1.3-2× more loved albums under the cap than the uncapped ranking, which ranks too many popular albums above them.
- **Inside a cap, the dampener hurts.** At caps of 1,000 and 200 it puts 17-39% of suggestions under 10 listeners and lowers recall.
- **A 10-listener floor** costs 0.001-0.004 recall and removes those suggestions.

### Decision (2026-11-02, proposed in ADR 0012)
Steps are no cap, 5,000, 1,000 and 200 listeners. Under a cap the engine ranks without the dampener and skips albums with fewer than 10 listeners.

### Limits
- One seed and 2,000 users. The differences that drive the decision are large, so the per-user confidence intervals of run 1 were not computed. The 3% cost of the floor at the 200 cap is within noise.
- Measured in model terms. The served cap uses catalog listeners (summed over editions), and the artist cap is not modelled.

## Run 4: 2026-11-03, album-page match score (ADR 0019)

`python -m recs.match --model-dir data/model --users 2000` (about 30 s). Each of 2,000 historical users has 20% of their albums hidden. The rest (or 10 random ones, like a site user's ratings) is the query. Every album at least `min support` of the query's nearest listeners have gets a percentile score, as on the album page. A good score puts the hidden albums, which the user really loves, near 100.

| Query | pop_beta | Neighbours | Min support | Hidden albums scored | Median score | Under 50 | Lift (95-100 vs 0-50) |
|---|---|---|---|---|---|---|---|
| all remaining | 0 | **300** | **2** | **68.9%** | **94.1** | 9.8% | 47.7x |
| all remaining | 0.25 | 300 | 2 | 68.9% | 95.0 | 9.1% | 54.7x |
| all remaining | 0 | 100 | 2 | 58.0% | 91.6 | 12.7% | 31.8x |
| all remaining | 0 | 100 | 1 | 68.0% | 95.9 | 9.1% | 58.4x |
| all remaining | 0 | 200 | 2 | 65.2% | 93.1 | 10.7% | 41.5x |
| all remaining | 0 | 500 | 3 | 68.9% | 93.5 | 10.6% | 42.6x |
| 10 albums | 0 | **300** | **2** | **64.7%** | **92.2** | 11.5% | 36.0x |
| 10 albums | 0.25 | 300 | 2 | 64.7% | 92.7 | 12.1% | 35.2x |
| 10 albums | 0 | 100 | 2 | 52.6% | 88.4 | 14.9% | 22.1x |
| 10 albums | 0 | 100 | 1 | 64.1% | 94.7 | 10.7% | 45.6x |
| 10 albums | 0 | 200 | 2 | 60.3% | 91.1 | 12.1% | 31.5x |
| 10 albums | 0 | 500 | 3 | 64.2% | 91.4 | 12.1% | 32.7x |

Lift: how much likelier an album scoring 95-100 is to be one of the user's hidden albums than one scoring under 50. Raw hit rates per band depend on how many albums get scored, so compare lifts and medians, not rates.

**Findings.**
- The score means what it says. Albums people love score a median of 92-94, and 95-100 albums are 36-48 times likelier to be loved than albums under 50.
- The popularity dampener makes no real difference here. It's slightly better with long queries and level with 10-album ones, which is what site users have. **Chosen: off (pop_beta 0)**, so classics your neighbours love aren't marked down.
- For You's 100 neighbours leave almost half of loved albums without a score. **Chosen: 300 neighbours, at least 2 of them holding the album.** That scores two thirds of loved albums and is better on every measure.
- One supporting listener scores slightly more albums at a similar lift. But "1 of your closest listeners has it" is too thin to explain a score, so 2 is kept.

## Run 5: 2026-11-09, filters on For You (ADR 0026)

Run with the first set of filters (genre, years, country, type). The album length filter was added later the same day and uses the same neighbourhoods. It wasn't measured separately.

`cd backend && PYTHONPATH=.:.. python experiments/for_you_filters.py` (about 2 minutes on the full data). 400 historical listeners with at least 20 albums, each **left out of their own neighbours**. 80% of their albums are the query, and the hidden 20% that pass a filter are the targets. Each version ranks 240 albums inside the filter. Recall is the share of those targets found in the first 24 (one page) and in all 240.

A first try without leaving listeners out found nearly 100% everywhere: each listener was their own nearest neighbour. Only the list lengths from that try are used below.

| Filter | Listeners with a target | K 100: @24 / @240 / length | K 100, then wider: @24 / @240 | **K 1000, then 5000: @24 / @240** |
|---|---|---|---|---|
| Jazz | 52 | 0.417 / 0.538 / 76 | 0.455 / 0.731 | **0.513 / 0.731** |
| Hip hop | 180 | 0.469 / 0.690 / 193 | 0.469 / 0.751 | 0.450 / **0.779** |
| Metal | 140 | 0.436 / 0.635 / 191 | 0.436 / 0.696 | **0.457 / 0.740** |
| 1970s | 57 | 0.532 / 0.754 / 117 | 0.549 / 0.876 | **0.572 / 0.873** |
| 2010s | 339 | 0.336 / 0.581 / 238 | 0.336 / 0.583 | 0.328 / **0.659** |
| Electronic, 1990s | 47 | 0.365 / 0.535 / 75 | 0.376 / 0.908 | **0.443 / 0.908** |
| Folk, 2000s | 35 | 0.536 / 0.686 / 62 | 0.536 / 0.886 | **0.650 / 0.886** |
| Jazz, 1960s | 1 | (too few) | | |

How full the list gets with the served engine (catalog terms, artist cap, 300 listeners, first try): K 100 alone averages 30 albums for jazz, 35 for the 1970s and 2 for jazz in the 1960s, and only 51%, 53% and 0% of listeners get a full first page. Filling from K 1000 and 5000 brings every one of these to 186-240 albums, except jazz in the 1960s at 44.

**Findings.**
- K 100 alone isn't enough under a filter. Lists run short, and it finds far fewer of the albums people love inside the filter (0.54 against 0.73 for jazz, 0.54 against 0.91 for electronic in the 1990s, across the whole list).
- Starting from K 1000 is as good or better than K 100 first, on both measures, for every filter but the two broadest, whose first page is 0.01-0.02 lower, within noise. **Chosen: K 1000, filled from K 5000** (`FILTER_K`).
- On the full data a filtered page takes 45-130 ms, about 210 ms combined with a How Well Known step.

### Limits
- Narrow filters have few test listeners (35-57), so their differences are rough.
- Model terms, without the artist cap or edition merging.

## Run 6: 2026-11-10, model comparison

`pip install -r recs/requirements-experiments.txt` (adds `implicit` for ALS), then `python -m recs.compare --model-dir data/model --users 5000 --out data/experiments` (about 1 h 40 min, mostly ALS fits). Raw rows in `compare_tuning.csv`, `compare.csv` and `compare.json`.

The served user kNN against five other families on the run 1 protocol: test listeners removed from training, 20% of each one's albums hidden, the rest as the query at weight 1.0. Every model uses the same weight matrix (linear rank and plays, α 0.5) and must fold in listeners it never trained on. Each family was tuned on seed 0 (5,000 listeners) and its best setting tested once on seed 1, avoiding the tuning listeners. Differences are per-listener paired against the served settings, with 95% intervals. EASE was left out: a dense 633K × 633K album matrix (about 1.6 TB).

**Tuning (seed 0, NDCG@20)**

| Family | Grid | Best | Worst |
|---|---|---|---|
| Popularity | | 0.0248 | |
| User kNN | K 50, 100, 200 × β 0, 0.25 | K 100, β 0.25: 0.2383 | K 200, β 0: 0.2252 |
| Item kNN, (q Cᵀ) C | β 0, 0.1, 0.25 | β 0: 0.2595 | β 0.25: 0.1364 |
| RP3beta | β 0.1, 0.25, 0.4 | β 0.1: 0.2014 | β 0.4: 0.1532 |
| PureSVD | k 128, 256, 512 | 256: 0.1835 | 128: 0.1748 |
| ALS (implicit, reg 0.01, 15 iterations) | 64/α 20, 128/α 20, 128/α 40, 256/α 20, 256/α 40 | 256, α 20: 0.2515 | 64: 0.1945 |

A 300-listener smoke run picked the grid edges first: the popularity adjustment hurt item kNN (β 0.5 scored 0.014) and ALS, and ALS and PureSVD were best at their largest sizes, so the grids were moved.

**Test (seed 1, 5,000 listeners)**

| Model | NDCG@20 | vs served | 10 albums | vs served, 10 albums | Recall@20 | Hit rate@20 | Distinct | Head share | Fit | Query |
|---|---|---|---|---|---|---|---|---|---|---|
| Popularity | 0.0258 | −0.2147 ± 0.0054 | 0.0235 | −0.1123 ± 0.0038 | 0.030 | 0.216 | 35 | 100% | 0 s | 5 ms |
| **User kNN, K 100, β 0.25 (served)** | **0.2405** | | **0.1358** | | 0.228 | 0.825 | 20,161 | 74.7% | 1 s | 5 ms |
| Item kNN, β 0 | 0.2595 | **+0.0190 ± 0.0028** | 0.1399 | **+0.0041 ± 0.0023** | 0.251 | 0.861 | 23,368 | 75.2% | 1 s | 32 ms |
| RP3beta, β 0.1 | 0.2055 | −0.0350 ± 0.0038 | 0.1329 | −0.0029 ± 0.0032 | 0.202 | 0.782 | 19,182 | 82.3% | 0.5 s | 33 ms |
| PureSVD, 256 | 0.1823 | −0.0582 ± 0.0044 | 0.0909 | −0.0449 ± 0.0032 | 0.175 | 0.700 | 2,693 | 99.8% | 47 s | 5 ms |
| ALS, 256, α 20 | 0.2511 | +0.0106 ± 0.0042 | 0.1342 | −0.0016 ± 0.0028 | 0.245 | 0.828 | 6,632 | 97.0% | 12 min | 6 ms |

Query times are per listener in batches of 200, on this Mac.

**Findings.**
- **Item kNN beats the served model**: +7.9% NDCG@20 on full queries and +3.0% on 10-album queries, both intervals clear of zero, with more distinct albums and the same head share. It is about 6× slower per query.
- ALS is ahead on full queries but level on 10-album ones, recommends a third as many distinct albums (97% from the top 1%) and was still improving at 256 factors, a 12-minute fit. PureSVD shares the hit bias with less accuracy.
- RP3beta is well behind on full queries but within noise at 10 albums.
- User kNN keeps its run 1 settings on the new tuning sample. Its neighbours also drive Because You Rated, the match score and filtered lists, so a switch to item kNN would have to rebuild those on album similarity.
- **Acted on (owner decision 2026-11-10, ADR 0028):** the site now serves item kNN, β 0. Its other uses of the old neighbours were rebuilt and checked in run 7.

### Limits
- One split per sample, small grids (3-6 settings per family). ALS was not tuned past 256 factors or on regularization.
- The 10-album check uses a random 10 of the query, not the albums a new user would pick first.
- Offline accuracy on historical top-50 lists, not measured on site users.

## Run 7: 2026-11-10, item kNN settings (ADR 0028)

`python -m recs.item_checks --model-dir data/model --users 2000 --out data/experiments` (about 25 minutes), then `--only floor` (about 5 minutes). Raw rows in `item_checks.csv` and `item_checks_floor.csv`. The settings chosen for user kNN in runs 1-4, checked on item kNN with the same leave-out split (seed 23, 2,000 listeners), on full queries and on 10 random albums.

**Weights (NDCG@20).**

| α | Full | 10 albums |
|---|---|---|
| 0 (plays only) | 0.2520 | **0.1411** |
| **0.5 (served)** | 0.2569 | 0.1406 |
| 1 (rank only) | **0.2596** | 0.1361 |

α 0.5 is within 0.003 of the best at both sizes and never the worst. **Kept.**

**Star weights (simulated stars as in run 2, NDCG@20).**

| Scheme | Full | 10 albums |
|---|---|---|
| Uniform | 0.2569 | 0.1406 |
| **Gentle (served)** | **0.2633** | **0.1437** |
| Linear | 0.2625 | 0.1415 |
| Steep | 0.2564 | 0.1342 |

**Kept.**

**How Well Known (recall@20 of hidden albums under the cap).**

| Cap | Uncapped | Cap | **Cap, 10-listener floor** |
|---|---|---|---|
| 5,000, full / 10 albums | 0.160 / 0.106 | 0.243 / 0.156 | **0.247 / 0.164** |
| 1,000 | 0.104 / 0.073 | 0.234 / 0.145 | **0.240 / 0.153** |
| 200 | 0.068 / 0.051 | 0.205 / 0.123 | **0.220 / 0.138** |

**Kept.**

**Match score reference set.** The share of the listeners holding a query album who must hold an album before it is scored. Any single co-listener (a 150-listener smoke run) put loved albums at a median of 99.7.

| Least share | Scored, full / 10 | Median, full / 10 | Lift 95-100 vs 0-50, full / 10 |
|---|---|---|---|
| **0.1%** | **75.8% / 76.5%** | 99.1 / 97.9 | **812 / 232** |
| 0.3% | 63.1% / 65.6% | 98.4 / 96.4 | 514 / 145 |
| 1% | 45.5% / 48.8% | 97.0 / 93.6 | 255 / 68 |
| 3% | 26.6% / 30.9% | 94.8 / 89.1 | 102 / 30 |

**Chosen: 0.1%**, and at least 3 listeners (`MATCH_SHARE`). It scored the most loved albums and separated best. The cost: loved albums sit higher than under user kNN (median 98 against 92 at 10 albums).

**Thinly held albums (NDCG@20; share of picks under 10 listeners without a rule).** Found after the switch: with few rated albums, cosine favours albums with 2-3 listeners who all share them. The owner saw For You picks with no match score.

| Rule | 3 albums | 10 albums | Full |
|---|---|---|---|
| None (21% / 15% / 8% of picks under 10 listeners) | 0.0846 | 0.1406 | 0.2569 |
| Floor 10 | 0.0911 | 0.1473 | **0.2605** |
| Floor 25 | **0.0922** | **0.1479** | 0.2594 |
| Match support | 0.0913 | 0.1470 | 0.2576 |
| **Match support, floor 10** | 0.0920 | 0.1473 | 0.2576 |

**Chosen: match support and a 10-listener floor** (`engine.SUPPORTED_ONLY`, `FLOOR`). It's as good as the best rule at 3 and 10 albums, which is where site users are, and guarantees every pick a match score. On full queries it's 0.003 below floor 10 alone. Checked live: a 3-album taste got 24 of 24 picks with a score.

### Limits
- 2,000 listeners and one split. Simulated stars, as in run 2.
- The floor rule changes run 6's item kNN number slightly. Run 6 had no rule.

## Run 8: 2026-11-10, Diversify on For You (ADR 0029)

`python -m recs.diversity --model-dir data/model --users 1000 --out data/experiments` (about 30 minutes; `diversity.csv`). This is maximal marginal relevance over the best 500 candidates, with the same rules as served (10-listener floor, match support). Each next pick maximizes `(1 − s) · score / best score − s · its highest cosine to the picks so far`. Similarity@20 is the mean cosine between pairs of the 20 picks. "Rated albums used" is the share of query albums (up to 20) that are the closest one to some pick.

| Strength s | NDCG@20 full / 10 | Hit rate full / 10 | Similarity@20 full / 10 | Rated albums used full / 10 | Head share full / 10 |
|---|---|---|---|---|---|
| 0 (normal list) | 0.249 / 0.146 | 0.849 / 0.746 | 0.129 / 0.135 | 47% / 57% | 82% / 74% |
| 0.3 | 0.263 / 0.148 | 0.874 / 0.763 | 0.103 / 0.111 | 57% / 68% | 81% / 73% |
| 0.5 (served at first) | 0.267 / 0.139 | 0.870 / 0.749 | 0.072 / 0.079 | 67% / 79% | 79% / 71% |
| **0.7 (served)** | **0.236 / 0.106** | 0.852 / 0.626 | **0.035 / 0.029** | **79% / 87%** | 74% / 63% |
| 0.8 | 0.203 / 0.085 | 0.819 / 0.511 | 0.018 / 0.014 | 84% / 88% | 68% / 58% |

**Findings.**
- **A little diversity helps accuracy.** At 0.3 the full-query NDCG@20 rises 5% and the 10-album one 1%: the normal list spends places on near-duplicates.
- **Chosen for the button: 0.5.** Picks are about 40% less alike, and four in five rated albums (with 10) lead a pick. Accuracy is +7% on full queries and −4% at 10 albums. At 0.7 the 10-album accuracy falls 27%.
- **Raised to 0.7 the same day** (owner request for less similar albums, ADR 0029 revision): picks about 75% less alike than the normal list, 87% of a 10-album taste's rated albums lead a pick, NDCG@20 −5% full and −27% at 10 albums.
- **Cost:** about 150-210 ms to re-rank one list, cached per taste. The normal list is unchanged. Re-ranking it by default at 0.3 would likely be a small gain. That wasn't done: it's a ranking change for the owner to decide.

### Limits
- 1,000 listeners, one split. Variety is measured by album similarity, not by genre or era.

## Run 9: 2026-11-10, support for smaller albums (Deep Cuts short of picks)

`python -m recs.support_rule --model-dir data/model --users 1500 --out data/experiments` (about 20 minutes; `support_rule.csv`). The owner reported that the Deep Cuts page wasn't full. Run 7's thin-album rule wants an album held by 0.1% of the listeners who have a query album: 65 to 130 people for an ordinary taste, more than most albums under 200 listeners have in all. A 10-album taste had 10 such albums left. Compared at every How Well Known cap, always with the 10-listener floor: the served rule, 3 co-listeners under a cap, and **the album's own share**, `need = max(3, min(0.1% of holders, f × its own listeners))`. "Found" is recall@20 of the hidden albums inside the cap. "Short" is the share of tastes with fewer than 240 albums left before the artist cap.

| Query, cap | Served: NDCG / found / short | Own 5%: NDCG / found / short |
|---|---|---|
| 10 albums, none | 0.1476 / 0.185 / 0.5% | 0.1476 / 0.186 / 0.5% |
| 10 albums, 5,000 | 0.1084 / 0.182 / 0.7% | 0.1086 / 0.183 / 0.7% |
| 10 albums, 1,000 | 0.0758 / 0.183 / 1.0% | 0.0770 / 0.187 / 1.0% |
| 10 albums, 200 | 0.0405 / 0.151 / **29%** | 0.0454 / **0.181** / 1.4% |
| 3 albums, none | 0.0959 / 0.119 / 4.7% | 0.0956 / 0.119 / 4.7% |
| 3 albums, 200 | 0.0260 / 0.099 / 20% | 0.0268 / 0.104 / 12% |
| Full, none | 0.2643 / 0.279 / 0.1% | 0.2673 / 0.284 / 0.1% |
| Full, 200 | 0.0517 / 0.168 / **60%** | 0.0742 / **0.270** / 0.3% |

3 co-listeners under a cap scored the same as own 5% under every cap (to 0.001). Own 10% was a little worse at 200.

**Chosen: own 5%** (`engine.OWN_SHARE`, ADR 0028 revision). It's as good as the best rule under every cap, the same or better at Anything, and the match score uses it too. An album page scores an album with that support, so every pick has a score, while the reference set the percentile is taken against stays at 0.1%. Live on the full data, a 3-album and a 10-album taste got 240 picks at every slider step, and the first 48 at each step all had a match score.

### Limits
- 1,500 listeners, one split.
- The 3-album lists still can't reach 240 albums at Deep Cuts for 12% of tastes, because so few listeners share three albums.
