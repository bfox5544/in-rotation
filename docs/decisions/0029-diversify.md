# 0029: Diversify on For You

Status: accepted (2026-11-10, owner request: "Can you add a diversify button on the For You page which will give the user more diverse picks.")

## The control
- A **Diversify** toggle in the For You toolbar, beside Filters. It turns amber while on, like other active filters.
- It lives in the URL as `?diverse=1`, so Back, reload and shared links keep it. Switching it returns to page 1.
- While it's on, a line under the toolbar says what it does.
- It combines with How Well Known and the filters.

## How it ranks (`recs.item_knn.diversify`, `Engine.recommend(diverse=True)`)
Maximal marginal relevance (Carbonell and Goldstein 1998) re-ranks the best `DIVERSE_POOL` (500) candidates, after exclusions, the floor and filters. The rest follow in score order, so all 240 places stay filled. Each next pick maximizes:

`(1 − s) · score / best score − s · (its highest cosine similarity to the picks so far)`, with `s = DIVERSITY = 0.7` (0.5 at first, see Revision).

So each pick has to be good *and* unlike what is already on the list. The similarity is the one the ranking uses, so "unlike" means "loved by different people", not a genre rule.

**Strength (run 8).** At 0.5, picks are about 40% less alike and four in five of a 10-album taste's rated albums lead a pick. NDCG@20 is +7% on full queries and −4% with 10 albums. At 0.7, the 10-album accuracy falls 27%.

## API
`GET /me/recommendations?diverse=true` (boolean, default false). The re-ranked order is cached per taste and candidate set, so paging doesn't redo it.

## Cost
About 150-210 ms for the first diversified page (a 500 × 500 similarity product plus the greedy pass). Later pages take about 35 ms.

## Limits
- Variety is measured by listener overlap, not by genre or decade.
- The first pick is always the top-scoring album.
- Ask doesn't offer it yet.

## Revision (2026-11-10): stronger, 0.7
The owner asked for stronger diversification ("less similar albums"), so the strength went from 0.5 to 0.7, the next point run 8 measured. Against the normal list, picks are now about 75% less alike (similarity@20 0.129 → 0.035 on full queries, 0.135 → 0.029 with 10 albums, against 0.072 / 0.079 at 0.5), and 87% of a 10-album taste's rated albums lead a pick (79% at 0.5). The cost is accuracy: NDCG@20 is −5% on full queries and −27% with 10 albums (hit rate 0.746 → 0.626), and the head share falls from 74% to 63%. That's acceptable for an opt-in button whose job is variety. The normal list is unchanged.
