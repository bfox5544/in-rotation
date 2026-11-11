"""Weighted user-based collaborative filtering (M4).

A Recommender is composed from three swappable parts, all chosen by RecommenderConfig,
so an experiment is a config change:

    WeightFn      interactions -> preference weight per (user, album)      recs.weights
    SimilarityFn  query vectors x historical users -> similarities
    Aggregator    the top-K neighbours' weights -> a score per album

A query is a sparse row vector over model album indexes (see recs.query). Scoring never
builds an all-pairs similarity matrix: each batch of queries is one sparse product against
the user x album matrix, then the top K users are kept.

No web or database imports here; the API calls into this module.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd
from scipy import sparse

from .matrix import to_csr
from .weights import WeightConfig, compute_weights


# ---- components -------------------------------------------------------------------------

class WeightFn(Protocol):
    def __call__(self, interactions: pd.DataFrame) -> np.ndarray: ...


@dataclass(frozen=True)
class RankPlayWeights:
    """alpha * rank score + (1 - alpha) * play score, as in recs.weights."""
    cfg: WeightConfig = WeightConfig()

    def __call__(self, interactions: pd.DataFrame) -> np.ndarray:
        return compute_weights(interactions, self.cfg)


class SimilarityFn(Protocol):
    def fit(self, R: sparse.csr_matrix) -> None: ...
    def __call__(self, Q: sparse.csr_matrix) -> np.ndarray: ...   # dense (n_queries, n_users)


@dataclass
class CosineSimilarity:
    """Asymmetric cosine: q.r / (|q|^(2a) |r|^(2(1-a))). a = 0.5 is plain cosine.

    a > 0.5 penalizes long or heavy user rows less, so neighbours are chosen more by overlap.
    """
    asymmetry: float = 0.5
    _rt: sparse.csr_matrix | None = field(default=None, repr=False)
    _scale: np.ndarray | None = field(default=None, repr=False)

    def fit(self, R: sparse.csr_matrix) -> None:
        norms = np.sqrt(R.multiply(R).sum(axis=1)).A1
        norms[norms == 0] = 1.0
        self._scale = (norms ** (-2.0 * (1.0 - self.asymmetry))).astype(np.float32)
        self._rt = R.T.tocsr()

    def __call__(self, Q: sparse.csr_matrix) -> np.ndarray:
        qn = np.sqrt(Q.multiply(Q).sum(axis=1)).A1
        qn[qn == 0] = 1.0
        dots = (Q @ self._rt).toarray()
        return dots * self._scale[None, :] * (qn ** (-2.0 * self.asymmetry)).astype(np.float32)[:, None]


class Aggregator(Protocol):
    def __call__(self, N: sparse.csr_matrix, R: sparse.csr_matrix, B: sparse.csr_matrix) -> np.ndarray: ...


@dataclass(frozen=True)
class WeightedSum:
    """score(album) = sum over neighbours of sim(u) * w(u, album)."""

    def __call__(self, N, R, B):
        return (N @ R).toarray()


@dataclass(frozen=True)
class NormalizedSum:
    """Weighted sum divided by the similarity mass of neighbours who have the album, plus `shrink`.

    Small shrink: average preference among neighbours who listen (favours niche agreement).
    Large shrink: approaches WeightedSum up to a constant.
    """
    shrink: float = 1.0

    def __call__(self, N, R, B):
        return (N @ R).toarray() / ((N @ B).toarray() + self.shrink)


# ---- configuration ----------------------------------------------------------------------

@dataclass(frozen=True)
class RecommenderConfig:
    weights: WeightConfig = WeightConfig()
    similarity: str = "cosine"
    asymmetry: float = 0.5        # CosineSimilarity; 0.5 = plain cosine
    k: int = 100                  # neighbours kept per query
    aggregator: str = "sum"       # sum | normalized
    shrink: float = 1.0           # NormalizedSum only
    pop_beta: float = 0.25        # divide scores by popularity ** beta; 0 = off. 0.25 chosen 2026-10-30 (docs/experiments.md)
    batch_size: int = 64          # queries per sparse product; bounds memory to about batch x n_users floats


SIMILARITIES = {"cosine": lambda c: CosineSimilarity(c.asymmetry)}
AGGREGATORS = {"sum": lambda c: WeightedSum(), "normalized": lambda c: NormalizedSum(c.shrink)}


def _make(registry: dict, name: str, cfg: RecommenderConfig):
    if name not in registry:
        raise ValueError(f"unknown component {name!r}; choose from {sorted(registry)}")
    return registry[name](cfg)


# ---- recommenders -----------------------------------------------------------------------

def _top_n(scores: np.ndarray, n: int, exclude: list[np.ndarray]) -> list[np.ndarray]:
    """Best n album indexes per row, highest first. Excluded or non-positive scores are never returned."""
    out = []
    for row, ex in zip(scores, exclude):
        row[ex] = 0.0
        m = min(n, int((row > 0).sum()))
        if m == 0:
            out.append(np.empty(0, dtype=np.int64))
            continue
        part = np.argpartition(-row, m - 1)[:m]
        out.append(part[np.argsort(-row[part], kind="stable")])
    return out


def _row_indices(Q: sparse.csr_matrix) -> list[np.ndarray]:
    return [Q.indices[Q.indptr[i]:Q.indptr[i + 1]] for i in range(Q.shape[0])]


class Recommender:
    def __init__(self, cfg: RecommenderConfig = RecommenderConfig(), weight_fn: WeightFn | None = None):
        self.cfg = cfg
        self.weight_fn = weight_fn or RankPlayWeights(cfg.weights)
        self.similarity: SimilarityFn = _make(SIMILARITIES, cfg.similarity, cfg)
        self.aggregator: Aggregator = _make(AGGREGATORS, cfg.aggregator, cfg)

    def fit(self, interactions: pd.DataFrame, n_albums: int | None = None, n_users: int | None = None) -> "Recommender":
        """interactions: user_idx, album_idx, rank, playcount (interactions.parquet)."""
        shape = (n_users or int(interactions["user_idx"].max()) + 1,
                 n_albums or int(interactions["album_idx"].max()) + 1)
        self.R = to_csr(interactions, self.weight_fn(interactions), shape)
        self.B = self.R.copy()
        self.B.data[:] = 1.0
        self.popularity = np.diff(self.R.tocsc().indptr).astype(np.float32)   # listeners per album
        self._damp = np.maximum(self.popularity, 1.0) ** -self.cfg.pop_beta if self.cfg.pop_beta else None
        self.similarity.fit(self.R)
        return self

    @classmethod
    def from_model_dir(cls, model_dir: str | Path, cfg: RecommenderConfig = RecommenderConfig()) -> "Recommender":
        d = Path(model_dir)
        n_albums = len(pd.read_parquet(d / "albums.parquet", columns=["album_idx"]))
        return cls(cfg).fit(pd.read_parquet(d / "interactions.parquet"), n_albums=n_albums)

    def reconfigure(self, **changes) -> "Recommender":
        """A copy sharing the fitted matrix, with different scoring settings (k, aggregator, shrink, pop_beta).

        Weights and similarity need a new fit; this is what lets the sweep reuse one neighbour search.
        """
        bad = set(changes) - {"k", "aggregator", "shrink", "pop_beta", "batch_size"}
        if bad:
            raise ValueError(f"{sorted(bad)} need a new fit")
        new = copy.copy(self)
        new.cfg = replace(self.cfg, **changes)
        new.aggregator = _make(AGGREGATORS, new.cfg.aggregator, new.cfg)
        new._damp = np.maximum(self.popularity, 1.0) ** -new.cfg.pop_beta if new.cfg.pop_beta else None
        return new

    @property
    def n_albums(self) -> int:
        return self.R.shape[1]

    def neighbours(self, Q: sparse.csr_matrix, k: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        """Top-k (user indexes, similarities) per query row, most similar first."""
        k = min(k or self.cfg.k, self.R.shape[0])
        idx_out, sim_out = [], []
        for start in range(0, Q.shape[0], self.cfg.batch_size):
            S = self.similarity(Q[start:start + self.cfg.batch_size])
            idx = np.argpartition(-S, k - 1, axis=1)[:, :k]
            sim = np.take_along_axis(S, idx, axis=1)
            order = np.argsort(-sim, axis=1, kind="stable")
            idx_out.append(np.take_along_axis(idx, order, axis=1))
            sim_out.append(np.take_along_axis(sim, order, axis=1))
        return np.vstack(idx_out), np.vstack(sim_out).astype(np.float32)

    def score(self, nbr_idx: np.ndarray, nbr_sim: np.ndarray) -> np.ndarray:
        """Dense (n_queries, n_albums) scores from precomputed neighbours. Slice the inputs to try a smaller K."""
        b, k = nbr_idx.shape
        N = sparse.csr_matrix((nbr_sim.ravel(), nbr_idx.ravel(), np.arange(0, b * k + 1, k)), shape=(b, self.R.shape[0]))
        scores = self.aggregator(N, self.R, self.B)
        if self._damp is not None:
            scores *= self._damp[None, :]
        return scores

    def recommend_batch(self, Q: sparse.csr_matrix, n: int = 20, exclude: list[np.ndarray] | None = None,
                        exclude_query: bool = True, neighbours: tuple[np.ndarray, np.ndarray] | None = None) -> list[np.ndarray]:
        """Top-n album indexes per query row.

        Albums in the query are excluded unless exclude_query is False (the rediscovery flag);
        `exclude` adds more per row (rated or listed albums). Pass `neighbours` to reuse a
        neighbour search, as the parameter sweep does.
        """
        nbr_idx, nbr_sim = neighbours if neighbours is not None else self.neighbours(Q)
        queried = _row_indices(Q) if exclude_query else [np.empty(0, np.int64)] * Q.shape[0]
        extra = exclude or [np.empty(0, np.int64)] * Q.shape[0]
        out: list[np.ndarray] = []
        for start in range(0, Q.shape[0], self.cfg.batch_size):
            end = start + self.cfg.batch_size
            ex = [np.concatenate([a, b]).astype(np.int64) for a, b in zip(queried[start:end], extra[start:end])]
            out.extend(_top_n(self.score(nbr_idx[start:end], nbr_sim[start:end]), n, ex))
        return out

    def recommend(self, query: sparse.csr_matrix, n: int = 20, exclude: np.ndarray | None = None,
                  exclude_query: bool = True) -> tuple[np.ndarray, np.ndarray]:
        """One query (1 x n_albums). Returns (album indexes, scores), best first."""
        nbr = self.neighbours(query)
        albums = self.recommend_batch(query, n, None if exclude is None else [np.asarray(exclude)], exclude_query, nbr)[0]
        return albums, self.score(*nbr)[0, albums]


class PopularityRecommender:
    """Baseline: most-listened albums the user hasn't picked. Every M4 result is compared to this."""

    def fit(self, interactions: pd.DataFrame, n_albums: int | None = None, n_users: int | None = None) -> "PopularityRecommender":
        n_albums = n_albums or int(interactions["album_idx"].max()) + 1
        self.popularity = np.bincount(interactions["album_idx"].to_numpy(), minlength=n_albums).astype(np.float32)
        return self

    def recommend_batch(self, Q: sparse.csr_matrix, n: int = 20, exclude: list[np.ndarray] | None = None,
                        exclude_query: bool = True, **_) -> list[np.ndarray]:
        queried = _row_indices(Q) if exclude_query else [np.empty(0, np.int64)] * Q.shape[0]
        extra = exclude or [np.empty(0, np.int64)] * Q.shape[0]
        head = np.argsort(-self.popularity, kind="stable")[: n + max((len(q) + len(e) for q, e in zip(queried, extra)), default=0)]
        out = []
        for q, e in zip(queried, extra):
            keep = head[~np.isin(head, np.concatenate([q, e]))]
            out.append(keep[self.popularity[keep] > 0][:n])
        return out
