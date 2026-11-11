"""Preference weights: how strongly a user's top-album entry says "they like this".

Weights are estimated strengths in (0, 1], not ratings. The rank function and the
rank/play blend are config, so M4 can sweep them without re-running preprocessing.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class WeightConfig:
    rank_fn: str = "linear"   # linear | log | exp
    alpha: float = 0.5        # share of the weight from rank; the rest comes from play count
    max_rank: int = 50
    decay: float = 0.08       # only used by "exp"


def _linear(rank: np.ndarray, cfg: WeightConfig) -> np.ndarray:
    return 1.0 - (rank - 1.0) / cfg.max_rank          # rank 1 -> 1.0, rank 50 -> 0.02


def _log(rank: np.ndarray, cfg: WeightConfig) -> np.ndarray:
    return 1.0 / np.log2(rank + 1.0)                  # rank 1 -> 1.0, rank 50 -> ~0.18


def _exp(rank: np.ndarray, cfg: WeightConfig) -> np.ndarray:
    return np.exp(-cfg.decay * (rank - 1.0))


RANK_FUNCTIONS: dict[str, Callable[[np.ndarray, WeightConfig], np.ndarray]] = {
    "linear": _linear,
    "log": _log,
    "exp": _exp,
}


def rank_score(rank: np.ndarray, cfg: WeightConfig) -> np.ndarray:
    if cfg.rank_fn not in RANK_FUNCTIONS:
        raise ValueError(f"unknown rank_fn {cfg.rank_fn!r}; choose from {sorted(RANK_FUNCTIONS)}")
    clipped = np.clip(np.asarray(rank, dtype=np.float64), 1, cfg.max_rank)
    return RANK_FUNCTIONS[cfg.rank_fn](clipped, cfg)


def play_score(user_idx: pd.Series, playcount: pd.Series) -> np.ndarray:
    """log(1 + plays), divided by that user's largest value so heavy listeners don't dominate."""
    logged = np.log1p(playcount.to_numpy(dtype=np.float64))
    top = pd.Series(logged).groupby(user_idx.to_numpy()).transform("max").to_numpy()
    return logged / top


def compute_weights(interactions: pd.DataFrame, cfg: WeightConfig = WeightConfig()) -> np.ndarray:
    """Columns needed: user_idx, rank, playcount. Returns float32 weights in (0, 1]."""
    if not 0.0 <= cfg.alpha <= 1.0:
        raise ValueError("alpha must be between 0 and 1")
    r = rank_score(interactions["rank"].to_numpy(), cfg)
    p = play_score(interactions["user_idx"], interactions["playcount"])
    return (cfg.alpha * r + (1.0 - cfg.alpha) * p).astype(np.float32)
