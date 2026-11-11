"""Turn a site user's picked albums into a query vector in model index space.

Each pick has weight 1.0 by default; M8 will pass rating-scaled weights instead. Albums
the model doesn't know are dropped and logged, never fatal: a user whose picks are all
unknown gets an empty query, and the caller falls back (for example to popularity).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse

log = logging.getLogger(__name__)


def query_matrix(picks: Sequence[Sequence[int]], n_albums: int,
                 weights: Sequence[Sequence[float]] | None = None) -> sparse.csr_matrix:
    """One row per user. Out-of-range indexes are dropped; a repeated album keeps its largest weight."""
    parts = []
    for i, albums in enumerate(picks):
        albums = np.asarray(albums, dtype=np.int64)
        w = np.ones(len(albums), np.float32) if weights is None else np.asarray(weights[i], np.float32)
        ok = (albums >= 0) & (albums < n_albums) & (w > 0)
        if not ok.all():
            log.warning("query %d: dropped %d album indexes outside the model or with weight <= 0", i, int((~ok).sum()))
        parts.append(pd.DataFrame({"row": i, "col": albums[ok], "w": w[ok]}))
    df = pd.concat(parts) if parts else pd.DataFrame({"row": [], "col": [], "w": []})
    df = df.groupby(["row", "col"], as_index=False)["w"].max()
    return sparse.csr_matrix((df["w"].to_numpy(np.float32), (df["row"].to_numpy(np.int64), df["col"].to_numpy(np.int64))),
                             shape=(len(picks), n_albums), dtype=np.float32)


def query_vector(album_idx: Iterable[int], n_albums: int, weights: Iterable[float] | None = None) -> sparse.csr_matrix:
    return query_matrix([list(album_idx)], n_albums, None if weights is None else [list(weights)])


class AlbumLookup:
    """Resolve album keys or MusicBrainz IDs to model indexes, from albums.parquet.

    M5 builds the full catalog-to-model mapping (album_id_map); this is the model side of it.
    """

    def __init__(self, albums: pd.DataFrame):
        self.albums = albums
        self._by_key = dict(zip(albums["album_key"], albums["album_idx"]))
        mb = albums.dropna(subset=["mbid"]).sort_values("n_users", ascending=False).drop_duplicates("mbid")
        self._by_mbid = dict(zip(mb["mbid"], mb["album_idx"]))

    @classmethod
    def from_model_dir(cls, model_dir: str | Path) -> "AlbumLookup":
        return cls(pd.read_parquet(Path(model_dir) / "albums.parquet"))

    def resolve(self, ids: Iterable[str]) -> tuple[list[int], list[str]]:
        """Each id is an album key ("artist | title") or an MBID. Returns (indexes, unmapped ids)."""
        found, missing = [], []
        for i in ids:
            idx = self._by_key.get(i, self._by_mbid.get(str(i).lower()))
            (found if idx is not None else missing).append(int(idx) if idx is not None else i)
        if missing:
            log.info("dropped %d album(s) with no model index: %s", len(missing), missing[:5])
        return found, missing
