"""Run 9: support for smaller albums (docs/experiments.md). The thin-album rule from run 7 wanted 0.1% of the
listeners who hold a query album, which no album under 200 listeners reaches for a big taste, so Deep Cuts lists
ran short. Compared at every How Well Known cap: the served rule, 3 co-listeners under a cap, and the album's
own 5% or 10% as an alternative (need = max(3, min(0.1% of holders, f x its own listeners))).

    python -m recs.support_rule --model-dir data/model --users 1500 --out data/experiments   # about 20 minutes

Counts only; no historical user is identified.
"""
import argparse, sys
from pathlib import Path
import json, time, numpy as np, pandas as pd
from .evaluate import EvalConfig, make_split, metrics
from .item_knn import ItemKNN
from .recommender import _top_n


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=1500)
    p.add_argument("--out", default="data/experiments")
    a = p.parse_args()
    meta = json.load(open(Path(a.model_dir) / "matrix_meta.json")); n_albums = meta["shape"][1]
    inter = pd.read_parquet(Path(a.model_dir) / "interactions.parquet")
    CAPS = (None, 5000, 1000, 200)
    RULES = ("served (0.1%)", "support 3 under a cap", "own 5%", "own 10%")
    rows = []
    for qname, m in (("3 albums", 3), ("10 albums", 10), ("all", None)):
        split = make_split(inter, n_albums, EvalConfig(n_users=a.users, seed=31, max_query=m))
        model = ItemKNN().fit(split.train, n_albums, split.n_users); pop = model.popularity.astype(float)
        acc = {(c, r): {"recall": [], "left": [], "recs": []} for c in CAPS for r in RULES}
        for start in range(0, len(split.users), 64):
            S = model.scores(split.Q[start:start + 64])
            for j, row in enumerate(S):
                i = start + j; q = split.Q[i].indices; hidden = split.hidden[i]
                sup = model.co_listeners(q); base = max(3, 0.001 * len(model.listeners(q)))
                for c in CAPS:
                    tail = hidden[(pop[hidden] <= (c or 1e12)) & (pop[hidden] >= 10)]
                    for r in RULES:
                        if r.startswith("served"): need = base
                        elif r.startswith("support 3"): need = base if c is None else 3
                        else: need = np.maximum(3, np.minimum(base, (0.05 if "5%" in r else 0.10) * pop))
                        drop = (pop < 10) | (sup < need)
                        if c: drop |= pop > c
                        drop[q] = True
                        acc[(c, r)]["left"].append(int((~drop).sum()))
                        top = _top_n(row[None, :].copy(), 20, [np.flatnonzero(drop).astype(np.int64)])[0]
                        acc[(c, r)]["recs"].append(top)
                        if len(tail): acc[(c, r)]["recall"].append(len(np.intersect1d(top, tail)) / len(tail))
            print(time.strftime("%H:%M:%S"), qname, min(start + 64, len(split.users)), flush=True)
        for (c, r), a in acc.items():
            mm = metrics(a["recs"], split.hidden, model.popularity, (20,))
            rows.append({"query": qname, "cap": c or "none", "rule": r, "ndcg@20": round(mm["ndcg@20"], 4),
                         "tail_recall@20": round(float(np.mean(a["recall"])), 4),
                         "share_under_240": round(float(np.mean(np.array(a["left"]) < 240)), 3)})
            print(json.dumps(rows[-1]), flush=True)
    df = pd.DataFrame(rows); df.to_csv(Path(a.out) / "support_rule.csv", index=False); print(df.to_string(index=False))


if __name__ == "__main__":
    main()
