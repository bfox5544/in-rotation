"""Refresh the catalog from the newest MusicBrainz dump, safely (M7, ADR 0007).

    python -m ingest.refresh --check     # is a newer dump out? exit 0 = up to date, 10 = newer available
    python -m ingest.refresh             # download, rebuild, sanity-check, swap in data/catalog.db
    python -m ingest.refresh --core      # also refresh the core tables (7.7 GB download)

Steps:
  1. Read LATEST from json-dumps/ and compare it with `dump_dir` in <mb-dir>/ingest_meta.json.
  2. Download release-group.tar.xz into <mb-dir>/staging/ and check it against that folder's SHA256SUMS.
     With --core, also download the full export's mbdump.tar.bz2 and extract the tables the catalog
     reads; without it the current core tables are reused (release links then lag a little).
  3. Parse to Parquet and build a new catalog next to the live one.
  4. Refuse to swap if listening coverage fell by more than MAX_COVERAGE_DROP or the catalog shrank by
     more than MAX_SHRINK (a broken or partial dump), unless --force. Nothing live is touched then.
  5. Swap: the live catalog becomes catalog.db.prev, the new one goes live, and the new Parquet and
     metadata replace the old. Downloads are deleted unless --keep-downloads.
The running API keeps serving the old file until it is restarted (it opens the catalog at startup).
Saved albums survive MusicBrainz merges through album_redirects; the report counts albums that
left the catalog without a redirect ("retired").

Only dumps are downloaded, never the live API. Schedule it with cron or launchd (README).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

from ingest.catalog import build
from ingest.musicbrainz import run as parse_dump

BASE_URL = "https://data.metabrainz.org/pub/musicbrainz/data"
USER_AGENT = "InRotation-catalog-refresh/0.7 (portfolio project)"
CORE_TABLES = ("release", "release_group", "artist_credit", "release_group_gid_redirect", "medium", "track", "medium_format",
               "genre", "l_genre_genre", "link", "link_type", "url", "l_release_url", "l_release_group_url")
MAX_COVERAGE_DROP = 0.01   # share of listening
MAX_SHRINK = 0.02          # share of catalog albums
NEWER_AVAILABLE = 10


def _open(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": USER_AGENT}), timeout=60)


def latest(base: str, folder: str) -> str:
    with _open(f"{base}/{folder}/LATEST") as r:
        return r.read().decode().strip()


def download(url: str, sums_url: str, dest: Path, log=print) -> None:
    """Stream to disk, then compare with the SHA256SUMS entry; a mismatch deletes the file and raises."""
    with _open(sums_url) as r:
        sums = {line.split()[1].lstrip("*"): line.split()[0] for line in r.read().decode().splitlines() if line.strip()}
    expected = sums.get(dest.name)
    if expected is None:
        raise RuntimeError(f"{dest.name} is not listed in {sums_url}")
    digest, done, last = hashlib.sha256(), 0, time.time()
    with _open(url) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if time.time() - last > 30:
                log(f"  {dest.name}: {done / 1e9:.2f} GB")
                last = time.time()
    if digest.hexdigest() != expected:
        dest.unlink()
        raise RuntimeError(f"Checksum mismatch for {dest.name}: the download was deleted. Try again later.")


def _report(path: Path) -> dict:
    if not path.exists():
        return {}
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return json.loads(db.execute("SELECT value FROM catalog_meta WHERE key = 'report'").fetchone()[0])
    finally:
        db.close()


def _ids(path: Path, sql: str) -> set[str]:
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {r[0] for r in db.execute(sql)}
    except sqlite3.OperationalError:   # an older catalog without album_redirects
        return set()
    finally:
        db.close()


def compare(old: Path, new: Path) -> dict:
    """What the swap would change: coverage, size, and albums that leave without a redirect."""
    before, after = _report(old), _report(new)
    gone = (_ids(old, "SELECT id FROM albums") - _ids(new, "SELECT id FROM albums")
            - _ids(new, "SELECT old_id FROM album_redirects")) if old.exists() else set()
    return {"listening_covered": [before.get("listening_covered"), after["listening_covered"]],
            "catalog_albums": [before.get("catalog_albums"), after["catalog_albums"]],
            "retired_albums": len(gone)}


def problems(change: dict) -> list[str]:
    (cov0, cov1), (n0, n1) = change["listening_covered"], change["catalog_albums"]
    out = []
    if cov0 is not None and cov1 < cov0 - MAX_COVERAGE_DROP:
        out.append(f"listening coverage fell from {cov0:.2%} to {cov1:.2%}")
    if n0 and n1 < n0 * (1 - MAX_SHRINK):
        out.append(f"catalog shrank from {n0:,} to {n1:,} albums")
    return out


def refresh(mb_dir: str = "data/musicbrainz", model_dir: str = "data/model", out: str = "data/catalog.db",
            base: str = BASE_URL, core: bool = False, force: bool = False, keep_downloads: bool = False,
            log=print) -> dict:
    mb, live = Path(mb_dir), Path(out)
    meta_path = mb / "ingest_meta.json"
    current = json.loads(meta_path.read_text()).get("dump_dir") if meta_path.exists() else None
    newest = latest(base, "json-dumps")
    if newest == current and not force:
        return {"status": "up to date", "dump_dir": current}

    staging = mb / "staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    log(f"downloading release groups from json-dumps/{newest}")
    dump = staging / "release-group.tar.xz"
    download(f"{base}/json-dumps/{newest}/release-group.tar.xz", f"{base}/json-dumps/{newest}/SHA256SUMS", dump, log)
    if core:
        full = latest(base, "fullexport")
        log(f"downloading core tables from fullexport/{full}")
        archive = staging / "mbdump.tar.bz2"
        download(f"{base}/fullexport/{full}/mbdump.tar.bz2", f"{base}/fullexport/{full}/SHA256SUMS", archive, log)
        wanted = {f"mbdump/{t}" for t in CORE_TABLES}
        with tarfile.open(archive, "r|bz2") as tar:
            for member in tar:
                if member.name in wanted and member.isfile():
                    tar.extract(member, staging / "core", filter="data")
    elif (mb / "core").exists():
        (staging / "core").symlink_to((mb / "core").resolve(), target_is_directory=True)

    log("parsing the dump")
    meta = parse_dump(str(dump), str(staging), log=log)
    meta["dump_dir"] = newest
    (staging / "ingest_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log("building the new catalog")
    candidate = live.with_name(live.name + ".new")
    report = build(model_dir, str(staging), str(candidate), log=log)
    change = compare(live, candidate)
    issues = problems(change)
    if issues and not force:
        return {"status": "refused", "dump_dir": newest, "problems": issues, "change": change,
                "kept_for_inspection": [str(candidate), str(staging)]}

    if live.exists():
        live.replace(live.with_name(live.name + ".prev"))
    candidate.replace(live)
    for name in ("release_groups.parquet", "artists.parquet", "ingest_meta.json"):
        (staging / name).replace(mb / name)
    if core:
        shutil.rmtree(mb / "core", ignore_errors=True)
        (staging / "core").replace(mb / "core")
    if keep_downloads:
        for f in staging.glob("*.tar.*"):
            f.replace(mb / f.name)
    shutil.rmtree(staging, ignore_errors=True)
    return {"status": "refreshed", "dump_dir": newest, "change": change, "problems": issues,
            "matched_share_1000_plus_listeners": report.get("matched_share_1000_plus_listeners"),
            "next": "Restart the API to serve the new catalog."}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mb-dir", default="data/musicbrainz")
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--out", default="data/catalog.db")
    p.add_argument("--base-url", default=BASE_URL)
    p.add_argument("--check", action="store_true", help="only report whether a newer dump exists")
    p.add_argument("--core", action="store_true", help="also refresh the core tables (7.7 GB)")
    p.add_argument("--force", action="store_true", help="rebuild even when up to date, and swap despite failed checks")
    p.add_argument("--keep-downloads", action="store_true")
    a = p.parse_args()
    if a.check:
        meta_path = Path(a.mb_dir) / "ingest_meta.json"
        current = json.loads(meta_path.read_text()).get("dump_dir") if meta_path.exists() else None
        newest = latest(a.base_url, "json-dumps")
        print(json.dumps({"current": current, "latest": newest}))
        sys.exit(0 if current == newest else NEWER_AVAILABLE)
    result = refresh(a.mb_dir, a.model_dir, a.out, a.base_url, a.core, a.force, a.keep_downloads)
    print(json.dumps(result, indent=2))
    sys.exit(1 if result["status"] == "refused" else 0)


if __name__ == "__main__":
    main()
