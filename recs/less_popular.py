"""How to recommend less popular albums people will still like (For you "depth", ADR 0012).

    python -m recs.less_popular --model-dir data/model --users 2000 --out data/experiments

For each listener cap, only the held-out albums at or under the cap count: those are the less
known albums the user turned out to love. Each method is scored on how many of them its top 20
finds (recall@20, hit rate), with the user's remaining albums as the query, or 10 of them. Methods:
a stronger popularity dampener alone (beta 0.5, 1.0), the cap on the served ranking (beta 0.25),
the cap without the dampener, and that plus a floor of MIN_LISTENERS listeners.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import EvalConfig, make_split
from .recommender import Recommender, RecommenderConfig

CAPS = (5000, 1000, 200)
MIN_LISTENERS = 10
# name -> (pop_beta, apply the cap, listener floor)
METHODS = {
    "dampener 0.5": (0.5, False, 0), "dampener 1.0": (1.0, False, 0),
    "cap": (0.25, True, 0), "cap, no dampener": (0.0, True, 0),
    "cap, no dampener, floor": (0.0, True, MIN_LISTENERS),
}


def experiment(interactions: pd.DataFrame, n_albums: int, users: int = 2000, seed: int = 11, log=print) -> pd.DataFrame:
    rows = []
    for max_query in (None, 10):
        split = make_split(interactions, n_albums, EvalConfig(n_users=users, seed=seed, max_query=max_query))
        base = Recommender(RecommenderConfig()).fit(split.train, n_albums, split.n_users)
        pop, nbr = base.popularity, base.neighbours(split.Q)
        for cap in CAPS:
            tail = [h[pop[h] <= cap] for h in split.hidden]
            has = [i for i, h in enumerate(tail) if len(h)]
            for name, (beta, capped, floor) in METHODS.items():
                out = np.flatnonzero((pop > cap) | (pop < floor)) if capped else np.empty(0, np.int64)
                recs = base.reconfigure(pop_beta=beta).recommend_batch(split.Q, 20, [out] * len(split.users), neighbours=nbr)
                hits = [len(np.intersect1d(recs[i], tail[i])) for i in has]
                listeners = np.concatenate([pop[r] for r in recs])
                rows.append({"query": "all" if max_query is None else f"{max_query} picks", "cap": cap, "method": name,
                             "tail_recall@20": np.mean([h / len(tail[i]) for h, i in zip(hits, has)]),
                             "tail_hit@20": np.mean([h > 0 for h in hits]),
                             "share_under_cap": np.mean(listeners <= cap),
                             "share_under_10_listeners": np.mean(listeners < 10),
                             "median_listeners": float(np.median(listeners))})
                log(f"{rows[-1]['query']:>8} cap {cap:>5} {name:24} recall {rows[-1]['tail_recall@20']:.4f} "
                    f"median listeners {rows[-1]['median_listeners']:.0f}")
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=2000)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--out", default="data/experiments")
    a = p.parse_args()
    meta = json.loads((Path(a.model_dir) / "matrix_meta.json").read_text())
    df = experiment(pd.read_parquet(Path(a.model_dir) / "interactions.parquet"), meta["shape"][1], a.users, a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "less_popular.csv", index=False)


if __name__ == "__main__":
    main()
