"""The Album Map (ADR 0022): album positions on a plane where albums sit close together when the same
people listen to them, and where to put genre names on it.

Pure NumPy/SciPy/scikit-learn: the catalog side (which albums, their genres, the output file) lives in
ingest.album_map. scikit-learn is imported inside the functions, so the API never needs it.

1. `album_vectors`: each map album becomes its column of the user x album weight matrix (editions and
   aliases that share a catalog album are summed), L2-normalized, so two albums' dot product is the
   cosine similarity of their listeners.
2. `embed`: truncated SVD to `dims` dimensions, rows normalized again (a denoised cosine space).
3. `layout`: t-SNE with the cosine metric to 2D, scaled into a 0-1000 square (aspect kept, centred).
4. `place_labels`: for each genre, the spot where it is both common and dominant, then a greedy pass
   that keeps labels apart, in tiers (tier 0 is shown fully zoomed out, later tiers as you zoom in).
"""
from __future__ import annotations

import numpy as np
from scipy import sparse

SIZE = 1000.0                 # map coordinates run 0..SIZE on the longer side


def album_vectors(matrix: sparse.spmatrix, groups: list[list[int]]) -> sparse.csr_matrix:
    """Rows = map albums (each a list of model album indexes), columns = users; rows L2-normalized."""
    rows = np.repeat(np.arange(len(groups)), [len(g) for g in groups])
    cols = np.fromiter((m for g in groups for m in g), dtype=np.int64, count=len(rows))
    pick = sparse.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(len(groups), matrix.shape[1]))
    x = (pick @ sparse.csr_matrix(matrix).T).tocsr()
    norms = np.sqrt(x.multiply(x).sum(axis=1)).A1
    norms[norms == 0] = 1.0
    return (sparse.diags((1.0 / norms).astype(np.float32)) @ x).tocsr()


def embed(vectors: sparse.spmatrix, dims: int = 64, seed: int = 0) -> np.ndarray:
    from sklearn.decomposition import TruncatedSVD
    dims = max(1, min(dims, min(vectors.shape) - 1))
    e = TruncatedSVD(dims, random_state=seed).fit_transform(vectors)
    norms = np.linalg.norm(e, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return e / norms


def layout(embedding: np.ndarray, perplexity: float = 40.0, seed: int = 0) -> np.ndarray:
    """t-SNE positions in [0, SIZE] (the longer side spans it; the shorter one is centred)."""
    from sklearn.manifold import TSNE
    perplexity = min(perplexity, max(2.0, (len(embedding) - 1) / 3))
    xy = TSNE(2, perplexity=perplexity, metric="cosine", init="pca", random_state=seed).fit_transform(embedding)
    return fit_square(xy)


def fit_square(xy: np.ndarray, margin: float = 0.02) -> np.ndarray:
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    span = float((hi - lo).max()) or 1.0
    inner = SIZE * (1 - 2 * margin)
    out = (xy - lo) / span * inner
    return out + (SIZE - (hi - lo) / span * inner) / 2


def _smoothed_counts(xy: np.ndarray, grid: int) -> np.ndarray:
    cell = np.clip((xy / SIZE * grid).astype(int), 0, grid - 1)
    h = np.zeros((grid, grid))
    np.add.at(h, (cell[:, 0], cell[:, 1]), 1.0)
    p = np.pad(h, 1)
    return sum(p[1 + dx:grid + 1 + dx, 1 + dy:grid + 1 + dy] for dx in (-1, 0, 1) for dy in (-1, 0, 1))


def place_labels(xy: np.ndarray, members: dict[str, np.ndarray], grid: int = 40, min_share: float = 0.5,
                 min_count: int = 8, spacing: tuple[float, ...] = (110.0, 55.0, 28.0),
                 weight: dict[str, float] | None = None) -> list[dict]:
    """[{name, x, y, tier}]. `members` maps a name (a genre, or anything else that groups albums) to its
    album indexes. A name's spot is the grid cell (3x3 smoothed) where count x share is
    highest, where it holds at least `min_share` of the albums and `min_count` of its own; the label sits
    on the most crowded of its albums near there. Spots are taken strongest first; a label goes in the first tier
    whose `spacing` (map units) it keeps from every label already placed in that tier or earlier.
    `weight` scales a name's score (below 1: it loses close calls)."""
    everyone = _smoothed_counts(xy, grid)
    spots = []
    for genre, idx in members.items():
        if len(idx) < min_count:
            continue
        own = _smoothed_counts(xy[idx], grid)
        share = np.divide(own, everyone, out=np.zeros_like(own), where=everyone > 0)
        score = np.where((share >= min_share) & (own >= min_count), own * share, 0.0)
        if score.max() <= 0:
            continue
        cx, cy = np.unravel_index(int(score.argmax()), score.shape)
        centre = (np.array([cx, cy]) + 0.5) * SIZE / grid
        # The label goes on the busiest of its albums near the peak, never in the gap between two groups.
        cell = SIZE / grid
        near = xy[idx][np.linalg.norm(xy[idx] - centre, axis=1) <= 1.5 * cell]
        if len(near):
            crowd = (np.linalg.norm(near[:, None, :] - near[None, :, :], axis=2) <= 0.75 * cell).sum(axis=1)
            at = near[int(crowd.argmax())]
        else:
            at = centre
        spots.append((float(score.max()) * (weight or {}).get(genre, 1.0), genre, at))
    spots.sort(key=lambda s: -s[0])
    placed: list[dict] = []
    for tier, gap in enumerate(spacing):
        for _, name, at in spots:
            if any(p["name"] == name for p in placed):
                continue
            if all(np.hypot(p["x"] - at[0], p["y"] - at[1]) >= gap for p in placed):
                placed.append({"name": name, "x": round(float(at[0]), 1), "y": round(float(at[1]), 1), "tier": tier})
    return placed
