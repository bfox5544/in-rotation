"""Match score: how well one album fits a listener's taste, 0-100 (album pages; ADR 0019).

The engine's raw scores only rank albums: their size depends on the query, so 0.8 means something
different for every user. The match score is instead a percentile: where the album's score falls among
every album the listener's nearest neighbours have (the "supported" albums), with the query's own albums
left out. 92 means it scores higher than 92% of them. Albums too few neighbours have get no score.

    python -m recs.match --model-dir data/model --users 2000 --out data/experiments

checks the score against held-out data: with part of each historical user's albums hidden, do the
hidden albums (ones they really love) get high scores, and how often is a high score a hidden album?
It compares the popularity dampener on and off, the number of neighbours, and the support needed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .evaluate import EvalConfig, make_split
from .recommender import Recommender, RecommenderConfig

POP_BETA = 0.0           # no popularity dampener: it made no difference to the score (run 4)
NEIGHBOURS = 300         # more than For you's 100: two thirds of loved albums get a score instead of 55% (run 4)
MIN_SUPPORT = 2          # neighbours that must have an album before it gets a score
BANDS = (0, 50, 70, 80, 90, 95, 100)


def support_counts(rec: Recommender, nbr_idx: np.ndarray) -> np.ndarray:
    """How many of these neighbours (one query's row of indexes) have each album."""
    return np.asarray(rec.B[nbr_idx].sum(axis=0)).ravel()


def reference(scores: np.ndarray, support: np.ndarray, exclude: np.ndarray, eligible: np.ndarray | None = None,
              min_support: int = MIN_SUPPORT) -> np.ndarray:
    """Sorted scores of the supported albums a match is measured against: at least `min_support`
    neighbours have them, they are not in the query (`exclude`), and (if given) `eligible` is true."""
    keep = support >= min_support
    if eligible is not None:
        keep &= eligible
    keep[exclude] = False
    return np.sort(scores[keep])


def percentile(ref: np.ndarray, score: float) -> float:
    """Midrank percentile of `score` in the sorted reference, 0-100 (ties count half)."""
    if len(ref) == 0:
        return 0.0
    below = np.searchsorted(ref, score, side="left")
    equal = np.searchsorted(ref, score, side="right") - below
    return float(100.0 * (below + 0.5 * equal) / len(ref))


# (pop_beta, neighbours, min support) settings compared by the experiment; the first is the one served.
SETTINGS = ((0.0, 300, 2), (0.25, 300, 2), (0.0, 100, 2), (0.0, 100, 1), (0.0, 200, 2), (0.0, 300, 3), (0.0, 500, 3))


def experiment(interactions: pd.DataFrame, n_albums: int, users: int = 2000, seed: int = 19, log=print) -> pd.DataFrame:
    """For each setting: the share of held-out albums that get a score, their median percentile, the share
    under 50, and the lift (how much likelier a 95-100 album is to be a held-out one than a 0-50 album).
    Raw hit rates per band depend on how many albums are scored, so compare lifts, not rates."""
    rows = []
    for max_query in (None, 10):
        split = make_split(interactions, n_albums, EvalConfig(n_users=users, seed=seed, max_query=max_query))
        base = Recommender(RecommenderConfig()).fit(split.train, n_albums, split.n_users)
        all_idx, all_sim = base.neighbours(split.Q, k=max(k for _, k, _ in SETTINGS))
        for beta, k, min_support in SETTINGS:
            rec = base.reconfigure(pop_beta=beta)
            hidden_pct, scored, total = [], 0, 0
            band_hidden, band_all = np.zeros(len(BANDS) - 1), np.zeros(len(BANDS) - 1)
            for i in range(len(split.users)):
                nbr_idx, nbr_sim = all_idx[i:i + 1, :k], all_sim[i:i + 1, :k]
                scores = rec.score(nbr_idx, nbr_sim)[0]
                support = support_counts(rec, nbr_idx[0])
                ref = reference(scores, support, split.Q[i].indices, min_support=min_support)
                if len(ref) == 0:
                    continue
                hidden = split.hidden[i]
                total += len(hidden)
                ok = hidden[support[hidden] >= min_support]
                scored += len(ok)
                pct = [percentile(ref, s) for s in scores[ok]]
                hidden_pct.extend(pct)
                band_all += np.histogram(100.0 * (np.arange(len(ref)) + 0.5) / len(ref), BANDS)[0]
                band_hidden += np.histogram(pct, BANDS)[0]
            hp, rate = np.array(hidden_pct), band_hidden / np.maximum(band_all, 1)
            row = {"query": "all remaining" if max_query is None else f"{max_query} albums", "pop_beta": beta,
                   "neighbours": k, "min_support": min_support, "scored": scored / max(total, 1),
                   "median_pct": float(np.median(hp)), "under_50": float((hp < 50).mean()),
                   "share_90_plus": float((hp >= 90).mean()), "lift_95_vs_0_50": float(rate[-1] / max(rate[0], 1e-9))}
            rows.append(row)
            log(json.dumps({k_: round(v, 3) if isinstance(v, float) else v for k_, v in row.items()}))
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=2000)
    p.add_argument("--out", default="data/experiments")
    a = p.parse_args()
    meta = json.loads((Path(a.model_dir) / "matrix_meta.json").read_text())
    interactions = pd.read_parquet(Path(a.model_dir) / "interactions.parquet")
    df = experiment(interactions, meta["shape"][1], a.users)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "match.csv", index=False)
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
