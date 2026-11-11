"""Leave-k-out evaluation and parameter sweep (M4).

    python -m recs.evaluate --model-dir data/model --users 5000 --out data/experiments

Protocol: sample historical users with at least `min_albums` albums, hide `holdout` of each
user's albums at random, query with the rest (weight 1.0 each, like a site user's picks),
and score the top-K list against the hidden albums. Evaluation users are removed from the
training matrix, so a query can never find its own full row.

The sweep tunes on one user sample and reports the chosen settings on a second, disjoint
sample, always next to the popularity baseline. Results go to --out as CSV, JSON and
Markdown; docs/experiments.md records the conclusions.
"""
from __future__ import annotations

import argparse
import itertools
import json
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from .query import query_matrix
from .recommender import PopularityRecommender, Recommender, RecommenderConfig
from .weights import WeightConfig


@dataclass(frozen=True)
class EvalConfig:
    n_users: int = 5000
    holdout: float = 0.2
    min_albums: int = 10
    ks: tuple[int, ...] = (10, 20)
    seed: int = 0
    head_share: float = 0.01   # "head" = this share of most-listened albums, for the popularity-bias metric
    max_query: int | None = None   # keep only this many random query albums, like a site user's few picks


@dataclass
class Split:
    train: pd.DataFrame
    users: np.ndarray            # evaluation user_idx values (absent from train)
    Q: sparse.csr_matrix         # one query row per evaluation user
    hidden: list[np.ndarray]     # hidden album indexes per evaluation user
    n_users: int
    n_albums: int


def make_split(interactions: pd.DataFrame, n_albums: int, cfg: EvalConfig = EvalConfig(),
               avoid_users: np.ndarray | None = None) -> Split:
    rng = np.random.default_rng(cfg.seed)
    sizes = interactions.groupby("user_idx").size()
    eligible = sizes.index[sizes >= cfg.min_albums].to_numpy()
    if avoid_users is not None:
        eligible = np.setdiff1d(eligible, avoid_users)
    users = np.sort(rng.choice(eligible, size=min(cfg.n_users, len(eligible)), replace=False))
    is_eval = interactions["user_idx"].isin(users).to_numpy()

    ev = interactions.loc[is_eval, ["user_idx", "album_idx"]].copy()
    ev["order"] = rng.random(len(ev))
    ev["order"] = ev.groupby("user_idx")["order"].rank(method="first")
    n_hide = np.maximum(1, np.round(ev.groupby("user_idx")["album_idx"].transform("size") * cfg.holdout))
    ev["hidden"] = ev["order"] <= n_hide
    ev = ev.sort_values(["user_idx", "order"])   # random order within each user, for max_query below
    pos = {u: i for i, u in enumerate(users)}
    picks: list[list[int]] = [[] for _ in users]
    hidden: list[list[int]] = [[] for _ in users]
    for u, a, h in ev[["user_idx", "album_idx", "hidden"]].itertuples(index=False):
        (hidden if h else picks)[pos[u]].append(a)
    if cfg.max_query is not None:   # a random subset of the user's remaining albums
        picks = [p[:cfg.max_query] for p in picks]
    return Split(train=interactions.loc[~is_eval].reset_index(drop=True), users=users,
                 Q=query_matrix(picks, n_albums), hidden=[np.asarray(h, np.int64) for h in hidden],
                 n_users=int(interactions["user_idx"].max()) + 1, n_albums=n_albums)


def metrics(recs: list[np.ndarray], hidden: list[np.ndarray], popularity: np.ndarray,
            ks: tuple[int, ...] = (10, 20), head_share: float = 0.01) -> dict[str, float]:
    """Precision, recall, NDCG and hit rate at each K (binary relevance), plus catalog coverage,
    mean listeners of recommended albums, and the share of recommendations from the popular head."""
    head_n = max(1, int(round(head_share * len(popularity))))
    head = np.zeros(len(popularity), bool)
    head[np.argsort(-popularity, kind="stable")[:head_n]] = True
    discounts = 1.0 / np.log2(np.arange(2, max(ks) + 2))
    out: dict[str, float] = {}
    for k in ks:
        p = r = n = hit = 0.0
        shown: list[np.ndarray] = []
        for rec, hid in zip(recs, hidden):
            top = rec[:k]
            rel = np.isin(top, hid)
            hits = rel.sum()
            p += hits / k
            r += hits / len(hid)
            n += (discounts[:len(top)][rel]).sum() / discounts[:min(k, len(hid))].sum()
            hit += hits > 0
            shown.append(top)
        u = len(recs)
        allrec = np.concatenate(shown) if shown else np.empty(0, np.int64)
        out.update({f"precision@{k}": p / u, f"recall@{k}": r / u, f"ndcg@{k}": n / u, f"hit_rate@{k}": hit / u,
                    f"distinct@{k}": float(len(np.unique(allrec))),
                    f"coverage@{k}": len(np.unique(allrec)) / len(popularity),
                    f"mean_pop@{k}": float(popularity[allrec].mean()) if len(allrec) else 0.0,
                    f"head_share@{k}": float(head[allrec].mean()) if len(allrec) else 0.0})
    out["empty_lists"] = float(sum(len(x) == 0 for x in recs))
    return out


def evaluate(model, split: Split, cfg: EvalConfig = EvalConfig(), neighbours=None) -> dict[str, float]:
    recs = model.recommend_batch(split.Q, max(cfg.ks), neighbours=neighbours)
    popularity = np.bincount(split.train["album_idx"].to_numpy(), minlength=split.n_albums).astype(np.float32)
    return metrics(recs, split.hidden, popularity, cfg.ks, cfg.head_share)


# ---- sweep ------------------------------------------------------------------------------

SCORING_GRID = {
    "k": [50, 100, 200, 500],
    "agg": [("sum", 0.0), ("normalized", 0.1), ("normalized", 1.0), ("normalized", 10.0)],
    "pop_beta": [0.0, 0.25, 0.5],
}
WEIGHT_GRID = {"rank_fn": ["linear", "log", "exp"], "alpha": [0.0, 0.5, 1.0]}
ASYMMETRY_GRID = [0.5, 0.75, 0.9]
TARGET = "ndcg@20"


def _row(stage: str, cfg: RecommenderConfig, m: dict) -> dict:
    return {"stage": stage, "rank_fn": cfg.weights.rank_fn, "alpha": cfg.weights.alpha, "asymmetry": cfg.asymmetry,
            "k": cfg.k, "aggregator": cfg.aggregator, "shrink": cfg.shrink if cfg.aggregator == "normalized" else None,
            "pop_beta": cfg.pop_beta, **m}


def _fit(split: Split, cfg: RecommenderConfig) -> Recommender:
    return Recommender(cfg).fit(split.train, split.n_albums, split.n_users)


def _scoring_sweep(stage: str, rec: Recommender, split: Split, ecfg: EvalConfig, grid: dict, log) -> list[dict]:
    nbr_idx, nbr_sim = rec.neighbours(split.Q, max(grid["k"]))
    rows = []
    for k, (agg, shrink), beta in itertools.product(grid["k"], grid["agg"], grid["pop_beta"]):
        variant = rec.reconfigure(k=k, aggregator=agg, shrink=shrink or rec.cfg.shrink, pop_beta=beta)
        m = evaluate(variant, split, ecfg, neighbours=(nbr_idx[:, :k], nbr_sim[:, :k]))
        rows.append(_row(stage, variant.cfg, m))
        log(f"  {stage} k={k} {agg}{'' if agg == 'sum' else f'(shrink={shrink})'} beta={beta}: {TARGET} {m[TARGET]:.4f}")
    return rows


def _best(rows: list[dict]) -> dict:
    return max(rows, key=lambda r: r[TARGET])


def _cfg_from_row(r: dict, base: RecommenderConfig) -> RecommenderConfig:
    return replace(base, weights=replace(base.weights, rank_fn=r["rank_fn"], alpha=r["alpha"]), asymmetry=r["asymmetry"],
                   k=int(r["k"]), aggregator=r["aggregator"], shrink=r["shrink"] if r["shrink"] is not None else base.shrink,
                   pop_beta=r["pop_beta"])


def sweep(interactions: pd.DataFrame, n_albums: int, ecfg: EvalConfig, log=print) -> tuple[list[dict], RecommenderConfig, Split]:
    """Staged search on the tuning sample:
    1. scoring (K x aggregator x pop_beta) with default weights and plain cosine;
    2. weights (rank_fn x alpha) with the best scoring, rescoring K/aggregator/beta at each;
    3. similarity asymmetry with the best of 2, rescoring again.
    """
    split = make_split(interactions, n_albums, ecfg)
    base = RecommenderConfig()
    rows = [_row("baseline", base, evaluate(PopularityRecommender().fit(split.train, n_albums), split, ecfg))]
    rows[0].update(rank_fn=None, alpha=None, asymmetry=None, k=None, aggregator="popularity", shrink=None, pop_beta=None)
    log(f"popularity baseline: {TARGET} {rows[0][TARGET]:.4f}")

    rows += _scoring_sweep("1-scoring", _fit(split, base), split, ecfg, SCORING_GRID, log)
    best = _best(rows[1:])
    narrow = {"k": sorted({best["k"], *[k for k in SCORING_GRID["k"] if k in (100, 200)]}),
              "agg": [(best["aggregator"], best["shrink"] or 0.0)], "pop_beta": sorted({0.0, best["pop_beta"]})}

    for rank_fn, alpha in itertools.product(WEIGHT_GRID["rank_fn"], WEIGHT_GRID["alpha"]):
        if (alpha == 0.0 and rank_fn != "linear") or (rank_fn, alpha) == (best["rank_fn"], best["alpha"]):
            continue   # alpha 0 ignores rank, so the rank function doesn't matter; stage 1 already ran the default
        cfg = replace(_cfg_from_row(best, base), weights=WeightConfig(rank_fn=rank_fn, alpha=alpha))
        rows += _scoring_sweep("2-weights", _fit(split, cfg), split, ecfg, narrow, log)
    best = _best(rows[1:])

    for a in ASYMMETRY_GRID:
        if a == best["asymmetry"]:
            continue
        cfg = replace(_cfg_from_row(best, base), asymmetry=a)
        rows += _scoring_sweep("3-similarity", _fit(split, cfg), split, ecfg, narrow, log)
    return rows, _cfg_from_row(_best(rows[1:]), base), split


def final_report(interactions: pd.DataFrame, n_albums: int, chosen: RecommenderConfig, ecfg: EvalConfig,
                 tune_users: np.ndarray, log=print) -> list[dict]:
    """Chosen settings vs defaults vs popularity on a disjoint user sample."""
    test_cfg = replace(ecfg, seed=ecfg.seed + 1)
    split = make_split(interactions, n_albums, test_cfg, avoid_users=tune_users)
    rows = []
    for name, model in [("popularity", PopularityRecommender().fit(split.train, n_albums)),
                        ("cf-defaults", _fit(split, RecommenderConfig())),
                        ("cf-chosen", _fit(split, chosen))]:
        m = evaluate(model, split, test_cfg)
        rows.append({"model": name, **m})
        log(f"test {name}: {TARGET} {m[TARGET]:.4f}")
    return rows


def _markdown(df: pd.DataFrame, cols: list[str]) -> str:
    view = df[cols].copy()
    for c in view.columns:
        if view[c].dtype.kind == "f":
            view[c] = view[c].map(lambda v: "" if pd.isna(v) else f"{v:.4f}" if abs(v) < 10 and v != int(v) else f"{v:,.0f}")
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join("" if v is None else str(v) for v in row) + " |" for row in view.itertuples(index=False)]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--out", default="data/experiments")
    p.add_argument("--users", type=int, default=EvalConfig.n_users)
    p.add_argument("--holdout", type=float, default=EvalConfig.holdout)
    p.add_argument("--seed", type=int, default=EvalConfig.seed)
    a = p.parse_args()
    ecfg = EvalConfig(n_users=a.users, holdout=a.holdout, seed=a.seed)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    started = time.time()
    log = lambda msg: print(f"[{time.time() - started:6.0f}s] {msg}", flush=True)

    d = Path(a.model_dir)
    interactions = pd.read_parquet(d / "interactions.parquet")
    n_albums = len(pd.read_parquet(d / "albums.parquet", columns=["album_idx"]))
    rows, chosen, tune = sweep(interactions, n_albums, ecfg, log)
    sweep_df = pd.DataFrame(rows)
    sweep_df.to_csv(out / "sweep.csv", index=False)
    final = pd.DataFrame(final_report(interactions, n_albums, chosen, ecfg, tune.users, log))
    final.to_csv(out / "final.csv", index=False)
    (out / "chosen_config.json").write_text(json.dumps({"recommender": asdict(chosen), "eval": asdict(ecfg),
                                                        "target": TARGET}, indent=2), encoding="utf-8")

    keys = ["rank_fn", "alpha", "asymmetry", "k", "aggregator", "shrink", "pop_beta"]
    shown = ["ndcg@20", "recall@20", "precision@10", "distinct@20", "head_share@20"]
    test_cols = ["model", "ndcg@10", "ndcg@20", "precision@10", "precision@20", "recall@10", "recall@20",
                 "hit_rate@20", "distinct@20", "mean_pop@20", "head_share@20"]
    top = sweep_df.sort_values(TARGET, ascending=False).head(15)
    md = [f"# Evaluation results\n\nTuning sample: {len(tune.users):,} users (seed {ecfg.seed}), holdout {ecfg.holdout:.0%}, "
          f"{len(rows) - 1} CF settings. Target: {TARGET}. Runtime {time.time() - started:,.0f} s.\n",
          "## Test sample (disjoint users)\n", _markdown(final, test_cols),
          "\n## Best 15 settings on the tuning sample\n", _markdown(top, ["stage", *keys, *shown]),
          "\n## Chosen\n", "```json", json.dumps(asdict(chosen), indent=2), "```\n"]
    (out / "results.md").write_text("\n".join(md), encoding="utf-8")
    log(f"done; see {out / 'results.md'}")


if __name__ == "__main__":
    main()
