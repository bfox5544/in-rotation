"""Item-based collaborative filtering: the served model since 2026-11-10 (docs/experiments.md runs 6 and 7).

An album is a column of the listener x album weight matrix (recs.weights). Two albums are similar when the
same listeners rank both highly: the cosine of their columns. A query (a listener's rated albums, weighted
by stars) scores every album by its summed similarity to the query albums:

    score(b) = sum over query albums a of q(a) * cos(a, b)  =  (q C^T) C,  C = columns scaled to length 1

so the 633K x 633K album similarity matrix is never stored: one query is two sparse products through the
listeners. No popularity adjustment: the cosine already divides by each album's size, and dividing again
cost accuracy (run 6: beta 0.1 -0.015 NDCG@20, beta 0.25 -0.12).

No web or database imports here; the API calls into this module.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from .matrix import to_csr
from .recommender import _row_indices, _top_n
from .weights import WeightConfig, compute_weights

BATCH = 64   # queries per product in recommend_batch; bounds memory to about BATCH x n_albums floats


class ItemKNN:
    def __init__(self, weights: WeightConfig = WeightConfig()):
        self.weights = weights

    def fit(self, interactions: pd.DataFrame, n_albums: int | None = None, n_users: int | None = None) -> "ItemKNN":
        """interactions: user_idx, album_idx, rank, playcount (interactions.parquet)."""
        shape = (n_users or int(interactions["user_idx"].max()) + 1,
                 n_albums or int(interactions["album_idx"].max()) + 1)
        return self.fit_matrix(to_csr(interactions, compute_weights(interactions, self.weights), shape))

    def fit_matrix(self, R: sparse.csr_matrix) -> "ItemKNN":
        """From a listener x album weight matrix. Keeps C (listeners x albums) and its transpose, about 2x R."""
        C = R.tocsc(copy=True).astype(np.float32)
        norms = np.sqrt(np.asarray(C.multiply(C).sum(axis=0)).ravel())
        C = C @ sparse.diags((1.0 / np.maximum(norms, 1e-12)).astype(np.float32))
        self.C = C.tocsr()
        self.CT = C.T.tocsr()                                          # albums x listeners
        self.popularity = np.diff(self.CT.indptr).astype(np.float32)   # listeners per album
        return self

    @classmethod
    def from_model_dir(cls, model_dir: str | Path, weights: WeightConfig = WeightConfig()) -> "ItemKNN":
        d = Path(model_dir)
        n_albums = len(pd.read_parquet(d / "albums.parquet", columns=["album_idx"]))
        return cls(weights).fit(pd.read_parquet(d / "interactions.parquet"), n_albums=n_albums)

    @property
    def n_albums(self) -> int:
        return self.C.shape[1]

    def scores(self, Q: sparse.csr_matrix) -> np.ndarray:
        """Dense (n_queries, n_albums) scores. The query's own albums score too; callers exclude them."""
        return ((Q.astype(np.float32) @ self.CT) @ self.C).toarray()

    def recommend_batch(self, Q: sparse.csr_matrix, n: int = 20, exclude: list[np.ndarray] | None = None,
                        exclude_query: bool = True, **_) -> list[np.ndarray]:
        """Top-n album indexes per query row, the same contract as Recommender.recommend_batch."""
        queried = _row_indices(Q) if exclude_query else [np.empty(0, np.int64)] * Q.shape[0]
        extra = exclude or [np.empty(0, np.int64)] * Q.shape[0]
        out: list[np.ndarray] = []
        for start in range(0, Q.shape[0], BATCH):
            end = start + BATCH
            ex = [np.concatenate([a, b]).astype(np.int64) for a, b in zip(queried[start:end], extra[start:end])]
            out.extend(_top_n(self.scores(Q[start:end]), n, ex))
        return out

    def recommend(self, query: sparse.csr_matrix, n: int = 20, exclude: np.ndarray | None = None,
                  exclude_query: bool = True, scores: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
        """One query (1 x n_albums). Returns (album indexes, scores), best first. Pass `scores` (from
        `scores(query)[0]`) to reuse them; they are not modified."""
        row = (self.scores(query)[0] if scores is None else scores).copy()
        ex = [query.indices if exclude_query else np.empty(0, np.int64)]
        if exclude is not None:
            ex.append(np.asarray(exclude, np.int64))
        albums = _top_n(row[None, :], n, [np.concatenate(ex).astype(np.int64)])[0]
        return albums, row[albums]

    def similarity(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Cosine similarity of albums a (rows) and b (columns), dense (len(a), len(b))."""
        return (self.CT[np.asarray(a, np.int64)] @ self.CT[np.asarray(b, np.int64)].T).toarray()

    def co_listeners(self, albums: np.ndarray) -> np.ndarray:
        """How many listeners who have any of `albums` also have each album: the evidence behind a score."""
        who = np.unique(self.CT[np.asarray(albums, np.int64)].indices)
        return np.bincount(self.C[who].indices, minlength=self.n_albums)

    def listeners(self, albums: np.ndarray) -> np.ndarray:
        """Listener indexes (never shown) holding any of these albums."""
        return np.unique(self.CT[np.asarray(albums, np.int64)].indices)


DIVERSITY = 0.7      # For You's Diversify: weight on "unlike the picks so far" (run 8; 0.5 until the owner asked for stronger)
DIVERSE_POOL = 500   # candidates the re-ranking chooses from


def diversify(model: ItemKNN, candidates: np.ndarray, scores: np.ndarray, n: int,
              strength: float = DIVERSITY) -> np.ndarray:
    """Maximal marginal relevance (Carbonell and Goldstein 1998) over the best candidates, best first:
    each next pick maximizes (1 - strength) * score / best score - strength * its highest cosine similarity
    to the picks already made. strength 0 keeps the order."""
    candidates = np.asarray(candidates, np.int64)
    if strength <= 0 or len(candidates) <= 1:
        return candidates[:n]
    rel = scores[candidates] / max(float(scores[candidates].max()), 1e-12)
    sim = model.similarity(candidates, candidates)
    np.fill_diagonal(sim, 0.0)
    chosen = [0]
    closest = sim[0].copy()                      # each candidate's highest similarity to the chosen ones
    free = np.ones(len(candidates), bool)
    free[0] = False
    while len(chosen) < min(n, len(candidates)):
        value = (1 - strength) * rel - strength * closest
        value[~free] = -np.inf
        i = int(np.argmax(value))
        chosen.append(i)
        free[i] = False
        np.maximum(closest, sim[i], out=closest)
    return candidates[chosen]
