"""Local cover cache (ADR 0011): layout shared with the API, plus a job that fills it ahead of time.

    python -m ingest.covers --top 5000        # fetch covers for the most-listened albums not cached yet

The Cover Art Archive answers through two redirects to archive.org and takes 3-6 seconds per
image, and the redirect can't be cached by browsers. So the API serves covers from
data/covers/<first two chars>/<release-group MBID>.jpg, and fetches from the archive only on a
miss. This job pre-fetches the albums people are most likely to see (Discover, search results and
recommendations lean heavily on popular albums). An album with no archived art gets an empty
.none marker, retried after MISSING_TTL.

Cover art belongs to its copyright holders; the Cover Art Archive doesn't license it. Caching
copies is fine for this non-commercial portfolio project; review before any public deployment.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SOURCE = "https://coverartarchive.org/release-group/{id}/front-250"
USER_AGENT = "InRotation/0.11 (portfolio project; cover cache)"
MISSING_TTL = 7 * 24 * 3600     # re-check albums without art after a week; art gets added over time
REPO = Path(__file__).resolve().parents[1]


def cache_dir() -> Path:
    return Path(os.environ.get("INROTATION_COVERS", str(REPO / "data" / "covers")))


def image_path(album_id: str, root: Path | None = None) -> Path:
    return (root or cache_dir()) / album_id[:2] / f"{album_id}.jpg"


def missing_path(album_id: str, root: Path | None = None) -> Path:
    return (root or cache_dir()) / album_id[:2] / f"{album_id}.none"


def known_missing(album_id: str, root: Path | None = None) -> bool:
    p = missing_path(album_id, root)
    return p.exists() and time.time() - p.stat().st_mtime < MISSING_TTL


def store(album_id: str, data: bytes | None, root: Path | None = None) -> None:
    """Write atomically, so a reader never sees half an image."""
    target = image_path(album_id, root) if data is not None else missing_path(album_id, root)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    tmp.write_bytes(data or b"")
    tmp.replace(target)
    if data is not None:
        missing_path(album_id, root).unlink(missing_ok=True)


def download(album_id: str, timeout: float = 30) -> bytes | None:
    """The 250 px front image, or None when the archive has no art. Other failures raise."""
    req = urllib.request.Request(SOURCE.format(id=album_id), headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def prefetch(catalog: str, top: int, workers: int = 8, root: Path | None = None, fetch=download, log=print) -> dict:
    db = sqlite3.connect(f"file:{catalog}?mode=ro", uri=True)
    ids = [r[0] for r in db.execute("SELECT id FROM albums ORDER BY popularity DESC LIMIT ?", (top,))]
    db.close()
    todo = [i for i in ids if not image_path(i, root).exists() and not known_missing(i, root)]
    counts = {"albums": len(ids), "already_cached": len(ids) - len(todo), "fetched": 0, "no_art": 0, "failed": 0}
    log(f"{len(todo):,} of {len(ids):,} covers to fetch with {workers} workers")

    def one(album_id: str) -> str:
        try:
            data = fetch(album_id)
        except Exception:
            return "failed"          # left uncached: the API or the next run tries again
        store(album_id, data, root)
        return "fetched" if data is not None else "no_art"

    started = time.time()
    with ThreadPoolExecutor(workers) as pool:
        for n, outcome in enumerate(pool.map(one, todo), start=1):
            counts[outcome] += 1
            if n % 500 == 0:
                log(f"  {n:,}/{len(todo):,} ({time.time() - started:.0f} s)")
    counts["seconds"] = round(time.time() - started)
    return counts


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--catalog", default="data/catalog.db")
    p.add_argument("--top", type=int, default=5000, help="most-listened albums to cover (about 40 KB each)")
    p.add_argument("--workers", type=int, default=8, help="parallel downloads; keep it modest, the archive is shared")
    a = p.parse_args()
    print(prefetch(a.catalog, a.top, a.workers))


if __name__ == "__main__":
    main()
