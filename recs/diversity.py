"""Run 8: For You's Diversify button, maximal marginal relevance on item kNN (docs/experiments.md).

    python -m recs.diversity --model-dir data/model --users 1000 --out data/experiments

Same leave-out split as recs.evaluate, on full queries and 10 random albums. For each strength, the top 20
re-ranked from the best DIVERSE_POOL candidates (as served: albums under 10 listeners, or held by under
0.1% of the listeners who have a query album, left out) is scored on:

    ndcg@20, hit_rate@20   accuracy against the hidden albums
    similarity@20          mean cosine similarity between pairs of the 20 picks (lower = more varied)
    seeds_used             share of the query albums (up to 20) that are the closest one to some pick
    head_share@20          share of picks from the 1% most-listened albums
    ms                     time to re-rank one list

Counts only; no historical user is identified.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import EvalConfig, make_split, metrics
from .item_knn import DIVERSE_POOL, ItemKNN, diversify
from .recommender import _top_n

STRENGTHS = (0.0, 0.3, 0.5, 0.7, 0.8)
FLOOR = 10
BATCH = 64


def experiment(interactions: pd.DataFrame, n_albums: int, users: int = 1000, seed: int = 29, log=print) -> pd.DataFrame:
    rows = []
    for name, m in (("all", None), ("10 albums", 10)):
        split = make_split(interactions, n_albums, EvalConfig(n_users=users, seed=seed, max_query=m))
        model = ItemKNN().fit(split.train, n_albums, split.n_users)
        pop = model.popularity
        recs = {s: [] for s in STRENGTHS}
        sims = {s: [] for s in STRENGTHS}
        seeds = {s: [] for s in STRENGTHS}
        ms = {s: [] for s in STRENGTHS}
        for start in range(0, len(split.users), BATCH):
            S = model.scores(split.Q[start:start + BATCH])
            for j, row in enumerate(S):
                q = split.Q[start + j].indices
                need = max(3, 0.001 * len(model.listeners(q)))
                thin = np.flatnonzero((pop < FLOOR) | (model.co_listeners(q) < need))
                pool = _top_n(row[None, :].copy(), DIVERSE_POOL, [np.concatenate([q, thin]).astype(np.int64)])[0]
                for s in STRENGTHS:
                    t = time.perf_counter()
                    top = diversify(model, pool, row, 20, s)
                    ms[s].append((time.perf_counter() - t) * 1000)
                    recs[s].append(top)
                    pair = model.similarity(top, top)
                    k = len(top)
                    sims[s].append((pair.sum() - np.trace(pair)) / max(k * (k - 1), 1))
                    lead = model.similarity(q, top).argmax(axis=0)
                    seeds[s].append(len(np.unique(lead)) / min(len(q), 20))
            log(f"  {name}: {min(start + BATCH, len(split.users))} of {len(split.users)}")
        for s in STRENGTHS:
            m_ = metrics(recs[s], split.hidden, pop, (20,))
            rows.append({"query": name, "strength": s, "ndcg@20": m_["ndcg@20"], "hit_rate@20": m_["hit_rate@20"],
                         "similarity@20": float(np.mean(sims[s])), "seeds_used": float(np.mean(seeds[s])),
                         "head_share@20": m_["head_share@20"], "distinct@20": m_["distinct@20"],
                         "ms": float(np.median(ms[s]))})
            log(json.dumps({k_: round(v, 4) if isinstance(v, float) else v for k_, v in rows[-1].items()}))
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=1000)
    p.add_argument("--out", default="data/experiments")
    a = p.parse_args()
    meta = json.loads((Path(a.model_dir) / "matrix_meta.json").read_text())
    interactions = pd.read_parquet(Path(a.model_dir) / "interactions.parquet")
    df = experiment(interactions, meta["shape"][1], a.users, log=lambda m: print(time.strftime("%H:%M:%S"), m, flush=True))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "diversity.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
