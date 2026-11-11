"""GET /api/covers/{album_id}: album covers from the local cache (ADR 0011, layout in ingest.covers).

A hit is served from disk in milliseconds with a 30-day browser cache. A miss fetches from the
Cover Art Archive once (3-6 s), stores it and serves it; concurrent requests for the same cover
share that one fetch. No archived art is a 404, remembered for a week, and the page shows its
generated artwork instead.
"""
import asyncio
import re

import httpx
from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import FileResponse

from ingest.covers import SOURCE, USER_AGENT, image_path, known_missing, store

from .catalog import get_catalog

router = APIRouter(prefix="/api")
MBID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
CACHED = {"Cache-Control": "public, max-age=2592000"}          # 30 days
NO_ART = {"Cache-Control": "public, max-age=86400"}            # ask again tomorrow
_client: httpx.AsyncClient | None = None
_inflight: dict[str, asyncio.Task] = {}


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(follow_redirects=True, timeout=30, headers={"User-Agent": USER_AGENT})
    return _client


async def fetch_cover(album_id: str) -> bytes | None:
    """The 250 px front image, or None when the archive has none. Other failures raise."""
    r = await _http().get(SOURCE.format(id=album_id))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


async def _fill(album_id: str) -> bytes | None:
    data = await fetch_cover(album_id)
    await asyncio.to_thread(store, album_id, data)
    return data


@router.get("/covers/{album_id}")
async def cover(album_id: str) -> Response:
    catalog = get_catalog()
    if not MBID.match(album_id) or not catalog.exists(album_id):
        raise HTTPException(404, "Album not found")
    album_id = catalog.canonical([album_id])[0]
    path = image_path(album_id)
    if path.exists():
        return FileResponse(path, media_type="image/jpeg", headers=CACHED)
    if known_missing(album_id):
        raise HTTPException(404, "No cover art", headers=NO_ART)
    task = _inflight.get(album_id)
    if task is None:
        task = _inflight[album_id] = asyncio.ensure_future(_fill(album_id))
        task.add_done_callback(lambda _: _inflight.pop(album_id, None))
    try:
        data = await asyncio.shield(task)
    except (httpx.HTTPError, OSError):
        raise HTTPException(502, "Cover Art Archive unavailable", headers={"Cache-Control": "no-store"})
    if data is None:
        raise HTTPException(404, "No cover art", headers=NO_ART)
    return Response(data, media_type="image/jpeg", headers=CACHED)
