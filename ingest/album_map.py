"""Build the Album Map (ADR 0022): the most-listened catalog albums laid out by who listens to them.

    python -m ingest.album_map                 # ~1-2 min on the full data; writes data/album_map.json
    python -m ingest.album_map --albums 15000

Reads data/model (the interactions, weighted as the engine weights them) and data/catalog.db, and uses recs.album_map for the maths.
Rebuild after the model or the catalog changes. The API reads the file at first request, resolves
MusicBrainz redirects and joins titles from the catalog, so a catalog refresh alone keeps it working.
The file holds album ids, positions, genre memberships and label spots only: no user data.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from recs import album_map
from recs.matrix import build_user_album_matrix
from recs.weights import WeightConfig

REPO = Path(__file__).resolve().parents[1]
ALBUMS = 15000          # map size: about the 15,000 most-listened albums (the cover cache holds the top 20,000)
MIN_LISTENERS = 20      # never map albums with fewer listeners than this, even in a small catalog
GENRE_MIN = 30          # a genre needs this many map albums to be offered or labelled
GENRES_OFFERED = 60     # genres in the "Highlight a Genre" list, most albums first
COUNTRY_BACKDROP = 2    # the most common countries on the map (US, UK) are never region labels
COUNTRY_WEIGHT = 0.6    # a genre wins a close call with a country for the same spot ("K-Pop" over "South Korea")


def map_path() -> Path:
    return Path(os.environ.get("INROTATION_MAP", str(REPO / "data" / "album_map.json")))


def build(catalog: str, model_dir: str, out: Path, albums: int = ALBUMS, dims: int = 64,
          perplexity: float = 40.0, genre_min: int = GENRE_MIN, log=print) -> dict:
    t0 = time.time()
    db = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    rows = db.execute("SELECT rowid, id FROM albums WHERE popularity >= ? ORDER BY popularity DESC, id LIMIT ?",
                      (MIN_LISTENERS, albums)).fetchall()
    pos = {album_id: i for i, (_, album_id) in enumerate(rows)}
    groups: list[list[int]] = [[] for _ in rows]
    for model_idx, album_id in db.execute("SELECT model_idx, album_id FROM album_id_map WHERE album_id IS NOT NULL"):
        if album_id in pos:
            groups[pos[album_id]].append(model_idx)
    keep = [i for i, g in enumerate(groups) if g]
    rows, groups = [rows[i] for i in keep], [groups[i] for i in keep]
    if len(rows) < 10:
        raise SystemExit(f"Only {len(rows)} albums have {MIN_LISTENERS}+ listeners; nothing to map.")

    # The same weights the API's engine fits (recs.weights defaults), from the interactions.
    interactions = pd.read_parquet(Path(model_dir) / "interactions.parquet")
    n_albums = len(pd.read_parquet(Path(model_dir) / "albums.parquet", columns=["album_idx"]))
    matrix = build_user_album_matrix(interactions, WeightConfig(), shape=(int(interactions["user_idx"].max()) + 1, n_albums))
    del interactions
    vectors = album_map.album_vectors(matrix, groups)
    log(f"{len(rows):,} albums, {vectors.nnz:,} listens ({time.time() - t0:.0f} s)")
    embedding = album_map.embed(vectors, dims)
    log(f"embedded in {dims} dimensions ({time.time() - t0:.0f} s)")
    xy = album_map.layout(embedding, perplexity)
    log(f"laid out ({time.time() - t0:.0f} s)")

    # Genre families: a genre includes its subgenres and fusions (album_family, ADR 0015).
    index_of = {rowid: i for i, (rowid, _) in enumerate(rows)}
    family: dict[str, list[int]] = {}
    marks = ",".join("?" * 999)
    rowids = [r for r, _ in rows]
    for start in range(0, len(rowids), 999):
        chunk = rowids[start:start + 999]
        for genre, rowid in db.execute(f"SELECT ancestor, album_rowid FROM album_family WHERE album_rowid IN ({marks[:2 * len(chunk) - 1]})", chunk):
            family.setdefault(genre, []).append(index_of[rowid])
    members = {g: np.array(sorted(ix)) for g, ix in family.items() if len(ix) >= genre_min}
    # Countries label regions no genre explains (Brazilian albums of every genre sit together). The
    # biggest COUNTRY_BACKDROP countries are everywhere, so they're never labels.
    countries: dict[str, list[int]] = {}
    for i, (rowid, _) in enumerate(rows):
        (code,) = db.execute("SELECT country FROM albums WHERE rowid = ?", (rowid,)).fetchone()
        if code:
            countries.setdefault(code, []).append(i)
    backdrop = sorted(countries, key=lambda c: -len(countries[c]))[:COUNTRY_BACKDROP]
    candidates = {**{f"genre:{g}": ix for g, ix in members.items()},
                  **{f"country:{c}": np.array(ix) for c, ix in countries.items() if c not in backdrop and len(ix) >= genre_min}}
    labels = []
    for label in album_map.place_labels(xy, candidates, weight={k: COUNTRY_WEIGHT for k in candidates if k.startswith("country:")}):
        kind, name = label.pop("name").split(":", 1)
        labels.append({"kind": kind, "name": name, **label})
    offered = sorted(members, key=lambda g: (-len(members[g]), g))[:GENRES_OFFERED]
    labelled = {label["name"] for label in labels if label["kind"] == "genre"}
    genres = {g: members[g].tolist() for g in dict.fromkeys([*offered, *sorted(labelled)])}

    doc = {
        "version": 1,
        "builtAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {"shape": list(matrix.shape), "nnz": int(matrix.nnz)},
        "settings": {"albums": albums, "dims": dims, "perplexity": perplexity, "genreMin": genre_min},
        "albums": [album_id for _, album_id in rows],
        "x": [round(float(v), 1) for v in xy[:, 0]],
        "y": [round(float(v), 1) for v in xy[:, 1]],
        "genres": genres,
        "labels": labels,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
    tmp.replace(out)
    stats = {"albums": len(rows), "genres": len(genres), "labels": len(labels), "seconds": round(time.time() - t0, 1),
             "bytes": out.stat().st_size}
    log(json.dumps(stats))
    return stats


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--catalog", default=str(REPO / "data" / "catalog.db"))
    p.add_argument("--model-dir", default=str(REPO / "data" / "model"))
    p.add_argument("--out", default=str(map_path()))
    p.add_argument("--albums", type=int, default=ALBUMS)
    p.add_argument("--dims", type=int, default=64)
    p.add_argument("--perplexity", type=float, default=40.0)
    a = p.parse_args()
    build(a.catalog, a.model_dir, Path(a.out), a.albums, a.dims, a.perplexity)


if __name__ == "__main__":
    main()
