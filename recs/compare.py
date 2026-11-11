"""Model comparison (run 6): the served user-kNN against other recommender families on the M4 protocol.

    python -m recs.compare --model-dir data/model --users 5000 --out data/experiments

Same leave-out protocol and metrics as recs.evaluate: test listeners are removed from training, 20% of each one's
albums are hidden, and the rest is the query at weight 1.0, like a site user's ratings. Every model gets the
same split, the same weight matrix (linear rank and plays, alpha 0.5) and the same option of the popularity
adjustment (score / listeners^beta), and must recommend for listeners it never trained on (fold-in):

    popularity  most-listened albums
    user-knn    the served engine (recs.recommender): cosine over listeners, K neighbours, weighted sum
    item-knn    item-based: sum of item-item cosine similarities to the query albums, computed through the
                listener matrix as (q C^T) C with C column-normalized, so no item x item matrix is stored
    rp3beta     random walk album -> listener -> album on the binary matrix (Paudel et al. 2017), / pop^beta
    puresvd     truncated SVD of the weight matrix (Cremonesi et al. 2010), scores q V V^T
    als         implicit ALS (Hu, Koren and Volinsky 2008) via the `implicit` library, query folded in with one
                least-squares solve per listener (needs `pip install implicit`; experiment only)

EASE is left out: it needs a dense album x album matrix, 633K x 633K here.

Each family is tuned on one sample of listeners (seed 0) and reported once on a disjoint sample (seed 1), with
per-listener paired differences against the served settings (95% intervals), a 10-album query check, and fit
and query times. Counts only; no historical user is identified.
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

from .evaluate import EvalConfig, Split, make_split, metrics
from .recommender import Recommender, RecommenderConfig

SERVED = RecommenderConfig()          # linear, alpha 0.5, cosine, K 100, weighted sum, beta 0.25
BATCH = 200


def _top(scores: np.ndarray, Q: sparse.csr_matrix, n: int) -> list[np.ndarray]:
    """Best n per row, the query's own albums excluded."""
    out = []
    for i in range(scores.shape[0]):
        row = scores[i]
        row[Q.indices[Q.indptr[i]:Q.indptr[i + 1]]] = -np.inf
        part = np.argpartition(-row, n - 1)[:n]
        out.append(part[np.argsort(-row[part], kind="stable")])
    return out


class Scored:
    """A model that produces dense scores for a batch of query rows; the popularity adjustment and top-n are shared."""
    name = "model"

    def __init__(self, beta: float = 0.0):
        self.beta = beta

    def fit(self, R: sparse.csr_matrix, popularity: np.ndarray) -> "Scored":
        self.damp = np.maximum(popularity, 1.0) ** -self.beta if self.beta else None
        return self

    def scores(self, Q: sparse.csr_matrix) -> np.ndarray:
        raise NotImplementedError

    def recommend_batch(self, Q: sparse.csr_matrix, n: int = 20, **_) -> list[np.ndarray]:
        out: list[np.ndarray] = []
        for s in range(0, Q.shape[0], BATCH):
            q = Q[s:s + BATCH]
            sc = np.asarray(self.scores(q), dtype=np.float64)
            if self.damp is not None:
                sc *= self.damp[None, :]   # applied to the raw scores, like the served engine
            out.extend(_top(sc, q, n))
        return out


class Popularity(Scored):
    name = "popularity"

    def fit(self, R, popularity):
        super().fit(R, popularity)
        self.pop = popularity.astype(np.float64)
        return self

    def scores(self, Q):
        return np.repeat(self.pop[None, :], Q.shape[0], axis=0)


class ItemKNN(Scored):
    name = "item-knn"

    def fit(self, R, popularity):
        super().fit(R, popularity)
        C = R.tocsc(copy=True).astype(np.float32)
        norms = np.sqrt(np.asarray(C.multiply(C).sum(axis=0)).ravel())
        C = C @ sparse.diags(1.0 / np.maximum(norms, 1e-12)).astype(np.float32)
        self.C = C.tocsr()
        self.CT = self.C.T.tocsr()
        return self

    def scores(self, Q):
        return ((Q.astype(np.float32) @ self.CT) @ self.C).toarray()


class RP3Beta(Scored):
    name = "rp3beta"

    def fit(self, R, popularity):
        super().fit(R, popularity)
        B = R.copy().astype(np.float32)
        B.data[:] = 1.0
        rows = np.asarray(B.sum(axis=1)).ravel()
        cols = np.asarray(B.sum(axis=0)).ravel()
        self.P_ui = (sparse.diags(1.0 / np.maximum(rows, 1)).astype(np.float32) @ B).tocsr()        # listener -> album
        self.P_iu = (sparse.diags(1.0 / np.maximum(cols, 1)).astype(np.float32) @ B.T.tocsr()).tocsr()  # album -> listener
        return self

    def scores(self, Q):
        Qb = Q.astype(np.float32)
        Qb = sparse.diags(1.0 / np.maximum(np.asarray(Qb.sum(axis=1)).ravel(), 1)).astype(np.float32) @ Qb
        return ((Qb @ self.P_iu) @ self.P_ui).toarray()


class PureSVD(Scored):
    name = "puresvd"

    def __init__(self, k: int = 128, beta: float = 0.0):
        super().__init__(beta)
        self.k = k

    def fit(self, R, popularity):
        from sklearn.utils.extmath import randomized_svd
        super().fit(R, popularity)
        _, _, VT = randomized_svd(R.astype(np.float32), self.k, n_iter=4, random_state=0)
        self.VT = VT.astype(np.float32)
        return self

    def scores(self, Q):
        return (Q.astype(np.float32) @ self.VT.T) @ self.VT


class ALS(Scored):
    name = "als"

    def __init__(self, factors: int = 128, alpha: float = 20.0, reg: float = 0.01, iterations: int = 15, beta: float = 0.0):
        super().__init__(beta)
        self.factors, self.alpha, self.reg, self.iterations = factors, alpha, reg, iterations

    def fit(self, R, popularity):
        from implicit.cpu.als import AlternatingLeastSquares
        super().fit(R, popularity)
        model = AlternatingLeastSquares(factors=self.factors, regularization=self.reg, alpha=self.alpha,
                                        iterations=self.iterations, random_state=0, calculate_training_loss=False)
        model.fit(R.astype(np.float32), show_progress=False)
        self.Y = np.asarray(model.item_factors, dtype=np.float64)
        self.YtY = self.Y.T @ self.Y
        return self

    def scores(self, Q):
        """Fold each query in: x = (Y^T C Y + reg I)^-1 Y^T C p, confidence 1 + alpha * weight (Hu et al.)."""
        k = self.Y.shape[1]
        X = np.empty((Q.shape[0], k))
        for i in range(Q.shape[0]):
            items = Q.indices[Q.indptr[i]:Q.indptr[i + 1]]
            conf = self.alpha * Q.data[Q.indptr[i]:Q.indptr[i + 1]]          # c - 1
            Yi = self.Y[items]
            A = self.YtY + (Yi.T * conf) @ Yi + self.reg * np.eye(k)
            X[i] = np.linalg.solve(A, Yi.T @ (1.0 + conf))
        return (X @ self.Y.T).astype(np.float32)


class UserKNN:
    """The served engine, through the same interface."""
    name = "user-knn"

    def __init__(self, k: int = 100, beta: float = 0.25):
        self.cfg = replace(SERVED, k=k, pop_beta=beta)
        self.beta = beta

    def fit_split(self, split: Split) -> "UserKNN":
        self.rec = Recommender(self.cfg).fit(split.train, split.n_albums, split.n_users)
        return self

    def recommend_batch(self, Q, n=20, **_):
        return self.rec.recommend_batch(Q, n)


# ---- protocol ---------------------------------------------------------------------------

def per_user_ndcg(recs: list[np.ndarray], hidden: list[np.ndarray], k: int = 20) -> np.ndarray:
    disc = 1.0 / np.log2(np.arange(2, k + 2))
    out = np.empty(len(recs))
    for i, (rec, hid) in enumerate(zip(recs, hidden)):
        rel = np.isin(rec[:k], hid)
        out[i] = disc[:len(rec[:k])][rel].sum() / disc[:min(k, len(hid))].sum()
    return out


def shared_matrix(split: Split) -> tuple[sparse.csr_matrix, np.ndarray]:
    """The served weight matrix and listener counts, built once per split and shared by every model."""
    rec = Recommender(SERVED).fit(split.train, split.n_albums, split.n_users)
    return rec.R.tocsr(), rec.popularity


def run(model, split: Split, R, popularity, ecfg: EvalConfig, log, fitted: bool = False) -> tuple[dict, list[np.ndarray], float, float]:
    t = time.perf_counter()
    if not fitted:
        model.fit_split(split) if isinstance(model, UserKNN) else model.fit(R, popularity)
    fit_s = time.perf_counter() - t
    t = time.perf_counter()
    recs = model.recommend_batch(split.Q, max(ecfg.ks))
    query_ms = (time.perf_counter() - t) * 1000 / len(recs)
    m = metrics(recs, split.hidden, popularity.astype(np.float32), ecfg.ks, ecfg.head_share)
    return m, recs, fit_s, query_ms


GRIDS = {   # tuned on the first sample. The 300-listener smoke run moved the edges: ALS and PureSVD did best at
            # the largest sizes tried, item-knn collapsed at beta 0.25, and ALS never gained from the adjustment.
    "popularity": [lambda: Popularity()],
    "user-knn": [lambda b=b, k=k: UserKNN(k, b) for k in (50, 100, 200) for b in (0.0, 0.25)],
    "item-knn": [lambda b=b: ItemKNN(b) for b in (0.0, 0.1, 0.25)],
    "rp3beta": [lambda b=b: RP3Beta(b) for b in (0.1, 0.25, 0.4)],
    "puresvd": [lambda k=k: PureSVD(k, 0.0) for k in (128, 256, 512)],
    "als": [lambda f=f, a=a: ALS(f, a, 0.01, 15, 0.0) for f, a in ((64, 20.0), (128, 20.0), (128, 40.0), (256, 20.0), (256, 40.0))],
}


def describe(m) -> str:
    if isinstance(m, UserKNN):
        return f"K {m.cfg.k}, beta {m.beta}"
    bits = [f"{a} {getattr(m, a)}" for a in ("k", "factors", "alpha") if hasattr(m, a)]
    return ", ".join(bits + [f"beta {m.beta}"])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--users", type=int, default=5000)
    p.add_argument("--out", default="data/experiments")
    p.add_argument("--families", default=",".join(GRIDS))
    a = p.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log = lambda s: print(time.strftime("%H:%M:%S"), s, flush=True)

    d = Path(a.model_dir)
    interactions = pd.read_parquet(d / "interactions.parquet")
    n_albums = len(pd.read_parquet(d / "albums.parquet", columns=["album_idx"]))
    ecfg = EvalConfig(n_users=a.users, seed=0)
    families = a.families.split(",")

    tune = make_split(interactions, n_albums, ecfg)
    R, pop = shared_matrix(tune)
    tuning, best = [], {}
    for fam in families:
        for make in GRIDS[fam]:
            model = make()
            m, _, fit_s, q_ms = run(model, tune, R, pop, ecfg, log)
            row = {"family": fam, "settings": describe(model), "ndcg@20": m["ndcg@20"], "recall@20": m["recall@20"],
                   "hit_rate@20": m["hit_rate@20"], "distinct@20": m["distinct@20"], "head_share@20": m["head_share@20"],
                   "fit_s": fit_s, "query_ms": q_ms}
            tuning.append(row)
            log(f"tune {fam:10} {row['settings']:28} ndcg@20 {m['ndcg@20']:.4f}  fit {fit_s:6.1f}s  {q_ms:6.1f} ms/query")
            if fam not in best or m["ndcg@20"] > best[fam][0]:
                best[fam] = (m["ndcg@20"], make)
    pd.DataFrame(tuning).to_csv(out / "compare_tuning.csv", index=False)
    del R

    test_cfg = replace(ecfg, seed=1)
    test = make_split(interactions, n_albums, test_cfg, avoid_users=tune.users)
    short = make_split(interactions, n_albums, replace(test_cfg, max_query=10), avoid_users=tune.users)
    assert np.array_equal(short.users, test.users)
    R, pop = shared_matrix(test)
    results, per_user = [], {}
    contenders = [("served", lambda: UserKNN(100, 0.25))] + [
        (f, best[f][1]) for f in families if not (f == "user-knn" and describe(best[f][1]()) == "K 100, beta 0.25")]
    for fam, make in contenders:
        model = make()
        m, recs, fit_s, q_ms = run(model, test, R, pop, test_cfg, log)
        m10, recs10, _, _ = run(model, short, R, pop, test_cfg, log, fitted=True)
        per_user[fam] = (per_user_ndcg(recs, test.hidden), per_user_ndcg(recs10, short.hidden))
        results.append({"family": fam, "settings": describe(model), **{k: m[k] for k in (
            "ndcg@20", "recall@20", "precision@10", "hit_rate@20", "distinct@20", "mean_pop@20", "head_share@20")},
            "ndcg@20_10albums": m10["ndcg@20"], "hit_rate@20_10albums": m10["hit_rate@20"],
            "fit_s": fit_s, "query_ms": q_ms})
        log(f"test {fam:10} {describe(model):28} ndcg@20 {m['ndcg@20']:.4f} (10 albums {m10['ndcg@20']:.4f})")
    base_all, base_10 = per_user["served"]
    for r in results:
        for suffix, (x, b) in (("", (per_user[r["family"]][0], base_all)), ("_10albums", (per_user[r["family"]][1], base_10))):
            diff = x - b
            r[f"vs_served{suffix}"] = float(diff.mean())
            r[f"vs_served_ci{suffix}"] = float(1.96 * diff.std(ddof=1) / np.sqrt(len(diff)))
    df = pd.DataFrame(results)
    df.to_csv(out / "compare.csv", index=False)
    (out / "compare.json").write_text(json.dumps({"users": int(len(test.users)), "seed_tune": 0, "seed_test": 1,
                                                  "results": results}, indent=2))
    log("\n" + df[["family", "settings", "ndcg@20", "vs_served", "vs_served_ci", "ndcg@20_10albums", "vs_served_10albums",
                   "vs_served_ci_10albums", "hit_rate@20", "distinct@20", "head_share@20", "fit_s", "query_ms"]].to_string(index=False))


if __name__ == "__main__":
    main()
