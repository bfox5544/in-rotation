"""Run 7: the settings chosen for the old user-kNN engine, checked again on item kNN (docs/experiments.md).

    python -m recs.item_checks --model-dir data/model --users 2000 --out data/experiments

Same leave-out split as recs.evaluate (20% hidden, test listeners out of training), on the full queries and on
10 random albums. Four questions, each a setting the site uses:

    weights   rank against plays in the album vectors: alpha 0 (plays only), 0.5 (served), 1 (rank only)
    ratings   star weights in the query (recs.ratings schemes on simulated stars, as in run 2)
    caps      How Well Known: recall@20 of held-out albums under each listener cap, ranked with the cap and
              the 10-listener floor, with the cap alone, or uncapped (as in run 3)
    match     the album-page match score: percentile of an album's score among the albums held by at least a
              share of the listeners who hold a query album (and MIN_SUPPORT of them), for several shares
              (as in run 4). Any album held by a single such listener would make nearly every score 99.
    floor     a least number of listeners for any recommended album (0, 10, 25), on full, 10- and 3-album
              queries: with few query albums, cosine favours albums with 2-3 listeners who all share them

Counts only; no historical user is identified.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from .evaluate import EvalConfig, evaluate, make_split, metrics
from .item_knn import ItemKNN
from .match import BANDS, percentile, reference
from .ratings import SCHEMES, stars_from_rank
from .recommender import _top_n
from .weights import WeightConfig

CAPS = (5000, 1000, 200)
FLOOR = 10
SUPPORTS = (0.001, 0.003, 0.01, 0.03)   # share of the listeners who hold a query album
MIN_SUPPORT = 3
BATCH = 64


def _weights(interactions, n_albums, splits, log) -> list[dict]:
    rows = []
    for alpha in (0.0, 0.5, 1.0):
        for name, split in splits.items():
            model = ItemKNN(WeightConfig(alpha=alpha)).fit(split.train, n_albums, split.n_users)
            m = evaluate(model, split)
            rows.append({"check": "weights", "query": name, "setting": f"alpha {alpha}", "ndcg@20": m["ndcg@20"],
                         "recall@20": m["recall@20"], "head_share@20": m["head_share@20"]})
            log(json.dumps(rows[-1]))
    return rows


def _ratings(interactions, splits, models, log) -> list[dict]:
    rank = interactions.set_index(["user_idx", "album_idx"])["rank"]
    rows = []
    for name, split in splits.items():
        Q = split.Q.tocoo()
        stars = stars_from_rank(rank.loc[list(zip(split.users[Q.row], Q.col))].to_numpy())
        for scheme, w in SCHEMES.items():
            Qw = sparse.csr_matrix((np.vectorize(w.get)(stars).astype(np.float32), (Q.row, Q.col)), shape=Q.shape)
            m = evaluate(models[name], replace(split, Q=Qw))
            rows.append({"check": "ratings", "query": name, "setting": scheme, "ndcg@20": m["ndcg@20"],
                         "recall@20": m["recall@20"]})
            log(json.dumps(rows[-1]))
    return rows


def _per_user(split, model, log) -> list[dict]:
    """Caps and match score from one set of scores per listener."""
    pop = model.popularity
    caps = {c: {"uncapped": [], "cap": [], "cap, floor": []} for c in CAPS}
    match = {s: {"pct": [], "scored": 0, "total": 0, "hid": np.zeros(len(BANDS) - 1), "all": np.zeros(len(BANDS) - 1)}
             for s in SUPPORTS}
    for start in range(0, len(split.users), BATCH):
        S = model.scores(split.Q[start:start + BATCH])
        for j, row in enumerate(S):
            i = start + j
            q, hidden = split.Q[i].indices, split.hidden[i]
            for cap, methods in caps.items():
                tail = hidden[pop[hidden] <= cap]
                if not len(tail):
                    continue
                for name, out in (("uncapped", q), ("cap", np.concatenate([q, np.flatnonzero(pop > cap)])),
                                  ("cap, floor", np.concatenate([q, np.flatnonzero((pop > cap) | (pop < FLOOR))]))):
                    top = _top_n(row[None, :].copy(), 20, [out.astype(np.int64)])[0]
                    methods[name].append(len(np.intersect1d(top, tail)) / len(tail))
            support = model.co_listeners(q)
            holders = len(model.listeners(q))
            for s, acc in match.items():
                need = max(MIN_SUPPORT, s * holders)
                ref = reference(row, support, q, min_support=need)
                if not len(ref):
                    continue
                acc["total"] += len(hidden)
                ok = hidden[support[hidden] >= need]
                acc["scored"] += len(ok)
                pct = [percentile(ref, v) for v in row[ok]]
                acc["pct"].extend(pct)
                acc["all"] += np.histogram(100.0 * (np.arange(len(ref)) + 0.5) / len(ref), BANDS)[0]
                acc["hid"] += np.histogram(pct, BANDS)[0]
        log(f"  {min(start + BATCH, len(split.users))} of {len(split.users)} listeners")
    rows = [{"check": "caps", "cap": c, "setting": n, "tail_recall@20": float(np.mean(v))}
            for c, methods in caps.items() for n, v in methods.items()]
    for s, acc in match.items():
        hp, rate = np.array(acc["pct"]), acc["hid"] / np.maximum(acc["all"], 1)
        rows.append({"check": "match", "setting": f"support {s:.1%} of holders", "scored": acc["scored"] / max(acc["total"], 1),
                     "median_pct": float(np.median(hp)), "under_50": float((hp < 50).mean()),
                     "share_90_plus": float((hp >= 90).mean()), "lift_95_vs_0_50": float(rate[-1] / max(rate[0], 1e-9))})
    return rows


# name -> (least listeners, require the match score's support: MATCH_SHARE of the listeners holding a query album)
FLOORS = {"none": (0, False), "floor 10": (10, False), "floor 25": (25, False),
          "match support": (0, True), "match support, floor 10": (10, True)}
MATCH_SHARE = 0.001


def floors(interactions: pd.DataFrame, n_albums: int, users: int = 2000, seed: int = 23, log=print) -> list[dict]:
    """NDCG@20, hit rate and the listeners of recommended albums for each way of leaving out thinly held albums."""
    rows = []
    for name, m in (("all", None), ("10 albums", 10), ("3 albums", 3)):
        split = make_split(interactions, n_albums, EvalConfig(n_users=users, seed=seed, max_query=m))
        model = ItemKNN().fit(split.train, n_albums, split.n_users)
        pop = model.popularity
        recs = {f: [] for f in FLOORS}
        for start in range(0, len(split.users), BATCH):
            S = model.scores(split.Q[start:start + BATCH])
            for j, row in enumerate(S):
                q = split.Q[start + j].indices
                support = model.co_listeners(q)
                need = max(MIN_SUPPORT, MATCH_SHARE * len(model.listeners(q)))
                for f, (least, supported) in FLOORS.items():
                    drop = pop < least
                    if supported:
                        drop |= support < need
                    out = np.concatenate([q, np.flatnonzero(drop)]).astype(np.int64)
                    recs[f].append(_top_n(row[None, :].copy(), 20, [out])[0])
        for f in FLOORS:
            m_ = metrics(recs[f], split.hidden, pop, (20,))
            listeners = np.concatenate([pop[r] for r in recs[f]])
            rows.append({"check": "floor", "query": name, "setting": f, "ndcg@20": m_["ndcg@20"],
                         "hit_rate@20": m_["hit_rate@20"], "head_share@20": m_["head_share@20"],
                         "share_under_10_listeners": float((listeners < 10).mean()),
                         "median_listeners": float(np.median(listeners))})
            log(json.dumps(rows[-1]))
    return rows


def experiment(interactions: pd.DataFrame, n_albums: int, users: int = 2000, seed: int = 23, log=print) -> pd.DataFrame:
    splits = {q: make_split(interactions, n_albums, EvalConfig(n_users=users, seed=seed, max_query=m))
              for q, m in (("all", None), ("10 albums", 10))}
    models = {q: ItemKNN().fit(s.train, n_albums, s.n_users) for q, s in splits.items()}
    rows = []
    for name, split in splits.items():
        started = time.time()
        log(f"caps and match, {name}")
        rows += [{"query": name, **r} for r in _per_user(split, models[name], log)]
        for r in rows[-(len(CAPS) * 3 + len(SUPPORTS)):]:
            log(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}))
        log(f"  {time.time() - started:.0f} s")
    rows += _ratings(interactions, splits, models, log)
    rows += _weights(interactions, n_albums, splits, log)
    rows += floors(interactions, n_albums, users, seed, log)
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=2000)
    p.add_argument("--out", default="data/experiments")
    p.add_argument("--only", choices=["floor"], help="run one check, written to item_checks_<check>.csv")
    a = p.parse_args()
    meta = json.loads((Path(a.model_dir) / "matrix_meta.json").read_text())
    interactions = pd.read_parquet(Path(a.model_dir) / "interactions.parquet")
    log = lambda m: print(time.strftime("%H:%M:%S"), m, flush=True)
    if a.only == "floor":
        df, name = pd.DataFrame(floors(interactions, meta["shape"][1], a.users, log=log)), "item_checks_floor.csv"
    else:
        df, name = experiment(interactions, meta["shape"][1], a.users, log=log), "item_checks.csv"
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / name, index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
