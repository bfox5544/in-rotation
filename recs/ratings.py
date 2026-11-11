"""Star ratings (0.5-5 in half stars) as query weights (M8, ADR 0008; half stars and no favorites: ADR 0009).

A site user's query is the albums they rated. Each album's weight comes from its stars, read off
the chosen scheme between whole stars (3 -> 0.6, 3.5 -> 0.7, ... 5 -> 1.0). Ratings below 3 are a
"not for me": the album is left out of the query and never recommended, but it is not used as a
negative signal, because the listening data has no dislikes to test that against.

    python -m recs.ratings --model-dir data/model --users 5000 --out data/experiments

runs the experiment behind the chosen weights: held-out users' top-50 ranks stand in for ratings
(rank 1-10 -> 5 stars, 11-25 -> 4, 26-50 -> 3) and each weighting scheme is scored with the M4
leave-out protocol, with all remaining albums and with 10, like a site user's picks.
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

from .evaluate import EvalConfig, evaluate, make_split
from .recommender import Recommender, RecommenderConfig

LIKED = 3.0            # ratings below this stay out of the query and out of recommendations
SCHEMES: dict[str, dict[int, float]] = {
    "uniform": {5: 1.0, 4: 1.0, 3: 1.0},
    "gentle": {5: 1.0, 4: 0.8, 3: 0.6},
    "linear": {5: 1.0, 4: 0.67, 3: 0.33},
    "steep": {5: 1.0, 4: 0.4, 3: 0.15},
}
CHOSEN = "gentle"      # see docs/experiments.md, "M8: rating weights"
RATING_WEIGHTS = SCHEMES[CHOSEN]


def query_weight(stars: float | None) -> float:
    """Weight of one album in the query: 0 means leave it out. Half stars sit between the
    whole-star weights the experiment chose (it simulated whole stars only)."""
    if stars is None or stars < LIKED:
        return 0.0
    whole = sorted(RATING_WEIGHTS)
    return float(np.interp(min(stars, 5.0), whole, [RATING_WEIGHTS[k] for k in whole]))


def stars_from_rank(rank: np.ndarray) -> np.ndarray:
    """Simulated ratings for the experiment: a top-10 album is a 5, 11-25 a 4, the rest a 3."""
    return np.select([rank <= 10, rank <= 25], [5, 4], 3)


def experiment(interactions: pd.DataFrame, n_albums: int, users: int = 5000, seed: int = 7,
               cfg: RecommenderConfig = RecommenderConfig(), log=print) -> pd.DataFrame:
    rank = interactions.set_index(["user_idx", "album_idx"])["rank"]
    rows = []
    for max_query in (None, 10):
        ecfg = EvalConfig(n_users=users, seed=seed, max_query=max_query)
        split = make_split(interactions, n_albums, ecfg)
        rec = Recommender(cfg).fit(split.train, n_albums, split.n_users)
        Q = split.Q.tocoo()
        stars = stars_from_rank(rank.loc[list(zip(split.users[Q.row], Q.col))].to_numpy())
        for name, scheme in SCHEMES.items():
            started = time.time()
            weights = np.vectorize(scheme.get)(stars).astype(np.float32)
            Qw = sparse.csr_matrix((weights, (Q.row, Q.col)), shape=Q.shape)
            m = evaluate(rec, replace(split, Q=Qw), ecfg)
            rows.append({"query": "all" if max_query is None else f"{max_query} picks", "scheme": name, **m})
            log(f"{rows[-1]['query']:>9} {name:8} ndcg@20 {m['ndcg@20']:.4f} recall@20 {m['recall@20']:.4f} "
                f"({time.time() - started:.0f} s)")
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=5000)
    p.add_argument("--seeds", type=int, nargs="+", default=[7, 8, 9])
    p.add_argument("--out", default="data/experiments")
    a = p.parse_args()
    meta = json.loads((Path(a.model_dir) / "matrix_meta.json").read_text())
    inter = pd.read_parquet(Path(a.model_dir) / "interactions.parquet")
    df = pd.concat([experiment(inter, meta["shape"][1], a.users, seed).assign(seed=seed) for seed in a.seeds])
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "rating_weights.csv", index=False)
    # Paired with uniform weights on the same users: mean difference and its spread over seeds.
    base = df[df.scheme == "uniform"].set_index(["seed", "query"])["ndcg@20"]
    df["vs_uniform"] = df["ndcg@20"].to_numpy() - base.loc[list(zip(df.seed, df["query"]))].to_numpy()
    summary = df.groupby(["query", "scheme"], sort=False).agg(
        ndcg20=("ndcg@20", "mean"), recall20=("recall@20", "mean"), vs_uniform=("vs_uniform", "mean"),
        vs_uniform_sd=("vs_uniform", "std"), mean_pop20=("mean_pop@20", "mean")).reset_index()
    summary.to_csv(out / "rating_weights_summary.csv", index=False)
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.4f}"))


if __name__ == "__main__":
    main()
