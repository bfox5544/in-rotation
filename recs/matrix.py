"""Build the sparse user x album weight matrix from the preprocessed interactions.

    python -m recs.matrix --model-dir data/model --rank-fn linear --alpha 0.5

Writes user_album.npz (CSR, float32, raw weights) and matrix_meta.json. Rows are
L2-normalized at query time (see l2_normalize_rows), so this file stays reusable
when M4 compares similarity functions.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

from .weights import WeightConfig, compute_weights


def build_user_album_matrix(interactions: pd.DataFrame, cfg: WeightConfig = WeightConfig(),
                            shape: tuple[int, int] | None = None) -> sparse.csr_matrix:
    return to_csr(interactions, compute_weights(interactions, cfg), shape)


def to_csr(interactions: pd.DataFrame, values: np.ndarray, shape: tuple[int, int] | None = None) -> sparse.csr_matrix:
    """user_idx x album_idx matrix of `values`. Pass `shape` when some users or albums have no rows."""
    if shape is None:
        shape = (int(interactions["user_idx"].max()) + 1, int(interactions["album_idx"].max()) + 1)
    coo = sparse.coo_matrix(
        (np.asarray(values, dtype=np.float32), (interactions["user_idx"].to_numpy(), interactions["album_idx"].to_numpy())),
        shape=shape, dtype=np.float32,
    )
    csr = coo.tocsr()
    csr.sum_duplicates()
    return csr


def l2_normalize_rows(m: sparse.csr_matrix) -> sparse.csr_matrix:
    norms = np.sqrt(m.multiply(m).sum(axis=1)).A1
    norms[norms == 0] = 1.0
    return sparse.diags((1.0 / norms).astype(np.float32)) @ m


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--rank-fn", default=WeightConfig.rank_fn, choices=["linear", "log", "exp"])
    p.add_argument("--alpha", type=float, default=WeightConfig.alpha)
    p.add_argument("--max-rank", type=int, default=WeightConfig.max_rank)
    p.add_argument("--decay", type=float, default=WeightConfig.decay)
    a = p.parse_args()
    cfg = WeightConfig(a.rank_fn, a.alpha, a.max_rank, a.decay)
    d = Path(a.model_dir)
    m = build_user_album_matrix(pd.read_parquet(d / "interactions.parquet"), cfg)
    sparse.save_npz(d / "user_album.npz", m, compressed=False)
    meta = {"shape": list(m.shape), "nnz": int(m.nnz), "weights": asdict(cfg),
            "approx_mb": round((m.data.nbytes + m.indices.nbytes + m.indptr.nbytes) / 1e6, 1)}
    (d / "matrix_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
