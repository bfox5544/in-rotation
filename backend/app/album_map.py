"""The Album Map (ADR 0022).

GET /api/map       every map album (id, title, artist, year, listeners, position), the genres you can
                   highlight (album positions in those columns, as gaps: -1 + steps[0], + steps[1] ...)
                   and the region labels. Built
                   offline by `python -m ingest.album_map`; 404 with that instruction until then.
GET /api/me/map    your For You ranking (top MAX_RECOMMENDATIONS ids), so the page can mark the picks
                   on the map. Unlike /me/recommendations it doesn't count them as shown (Insights).

The file holds ids only. Titles come from the catalog when it is first read, after resolving
MusicBrainz redirects, so a catalog refresh doesn't need a map rebuild; albums the catalog no longer has
are dropped. The response is built once, gzipped once, and cached by the browser for a day.
"""
import gzip
import hashlib
import json
import logging
import threading

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel

from ingest.album_map import map_path

from .auth import CurrentUser
from .catalog import get_catalog
from .db import DB
from .engine import get_engine
from .routes import MAX_RECOMMENDATIONS, _ratings, excluded, liked_seeds

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
CACHE = "public, max-age=86400"
_lock = threading.Lock()
_built: dict = {}


def _load() -> dict | None:
    """{etag, plain, gzipped} for the current file, rebuilt when the file changes; None without one."""
    path = map_path()
    if not path.exists():
        return None
    stamp = f"{path}:{path.stat().st_mtime_ns}-{path.stat().st_size}"
    with _lock:
        if _built.get("stamp") == stamp:
            return _built
        doc = json.loads(path.read_text(encoding="utf-8"))
        body = json.dumps(_payload(doc), separators=(",", ":"), ensure_ascii=False).encode()
        _built.clear()
        _built.update(stamp=stamp, etag=f'"{hashlib.sha1(body).hexdigest()[:16]}"', plain=body,
                      gzipped=gzip.compress(body, 6))
        log.info("album map: %s bytes, %s gzipped", len(body), len(_built["gzipped"]))
        return _built


def _payload(doc: dict) -> dict:
    catalog = get_catalog()
    current = catalog.canonical_each(doc["albums"])
    found: dict[str, tuple] = {}
    for start in range(0, len(current), 900):
        chunk = current[start:start + 900]
        for r in catalog._query(f"SELECT id, title, artist, year, popularity FROM albums WHERE id IN ({','.join('?' * len(chunk))})",
                                tuple(chunk)):
            found[r["id"]] = (r["title"], r["artist"], r["year"], r["popularity"])
    cols = {k: [] for k in ("id", "title", "artist", "year", "listeners", "x", "y")}
    new_index: dict[int, int] = {}
    for i, album_id in enumerate(current):
        if album_id not in found:
            continue
        title, artist, year, listeners = found.pop(album_id)   # pop: a merged duplicate keeps only its first spot
        new_index[i] = len(cols["id"])
        for k, v in zip(cols, (album_id, title, artist, year, listeners, doc["x"][i], doc["y"][i])):
            cols[k].append(v)
    dropped = len(current) - len(cols["id"])
    if dropped:
        log.warning("album map: %s albums are no longer in the catalog; rebuild with python -m ingest.album_map", dropped)
    # Genre members as gaps between sorted positions (the first counts from -1): a third of the size gzipped.
    genres = []
    for g, ix in doc["genres"].items():
        kept = sorted(new_index[i] for i in ix if i in new_index)
        genres.append({"name": g, "steps": [b - a for a, b in zip([-1, *kept], kept)]})
    return {"builtAt": doc["builtAt"], "albums": cols, "genres": genres, "labels": doc["labels"]}


@router.get("/map")
def album_map(accept_encoding: str = Header(""), if_none_match: str = Header("")) -> Response:
    built = _load()
    if built is None:
        raise HTTPException(404, "The album map hasn't been built yet. Run python -m ingest.album_map from the repo root.")
    headers = {"Cache-Control": CACHE, "ETag": built["etag"], "Vary": "Accept-Encoding"}
    if if_none_match == built["etag"]:
        return Response(status_code=304, headers=headers)
    if "gzip" in accept_encoding:
        return Response(built["gzipped"], media_type="application/json", headers={**headers, "Content-Encoding": "gzip"})
    return Response(built["plain"], media_type="application/json", headers=headers)


class MyMap(BaseModel):
    recommended: list[str]   # For You order, best first


@router.get("/me/map", response_model=MyMap)
def my_map(user: CurrentUser, db: DB) -> MyMap:
    ratings = _ratings(db, user)
    seeds = liked_seeds(ratings)
    if not seeds:
        return MyMap(recommended=[])
    return MyMap(recommended=get_engine().recommend(seeds, exclude=excluded(db, user, ratings), n=MAX_RECOMMENDATIONS))
