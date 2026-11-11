"""Package the data the API needs into one versioned bundle for the server (M9, ADR 0025).

    python -m ingest.release                    # -> dist/releases/inrotation-data-<version>.tar.gz

The bundle holds model/albums.parquet and model/interactions.parquet (the API rebuilds the weighted matrix
from them at startup), model/report.json, catalog.db and album_map.json, plus manifest.json: the version, when
and from what it was built, and each file's size and SHA-256. deploy/install-data.sh checks those hashes on the
server before switching to it, and keeps earlier versions for rollback. Covers aren't included: they're keyed
by album and survive model changes, so they're copied to the server separately.
"""
import argparse
import hashlib
import json
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FILES = ["model/albums.parquet", "model/interactions.parquet", "model/report.json", "catalog.db", "album_map.json"]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest(data: Path, version: str) -> dict:
    missing = [f for f in FILES if not (data / f).exists()]
    if missing:
        raise SystemExit(f"Missing in {data}: {', '.join(missing)}. Build them first (README: Build the catalog, Album Map).")
    with sqlite3.connect(f"file:{data / 'catalog.db'}?mode=ro", uri=True) as db:
        meta = dict(db.execute("SELECT key, value FROM catalog_meta").fetchall())
        albums = db.execute("SELECT count(*) FROM albums").fetchone()[0]
    model = json.loads((data / "model/report.json").read_text())
    return {
        "version": version,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "catalog": {"schema_version": meta.get("schema_version"), "albums": albums, "built_at": meta.get("built_at"),
                    "source": json.loads(meta.get("source") or "{}")},
        "model": model.get("kept", {}),
        "files": {f: {"bytes": (data / f).stat().st_size, "sha256": sha256(data / f)} for f in FILES},
    }


def main() -> None:
    p = argparse.ArgumentParser(description="Package model + catalog + map into a versioned bundle for deploy/install-data.sh.")
    p.add_argument("--data", default=str(REPO / "data"))
    p.add_argument("--out", default=str(REPO / "dist" / "releases"))
    p.add_argument("--version", default=datetime.now(timezone.utc).strftime("%Y%m%d-%H%M"))
    a = p.parse_args()
    data, out = Path(a.data), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    m = manifest(data, a.version)
    (out / f"manifest-{a.version}.json").write_text(json.dumps(m, indent=2))
    bundle = out / f"inrotation-data-{a.version}.tar.gz"
    with tarfile.open(bundle, "w:gz", compresslevel=6) as tar:
        manifest_file = out / f"manifest-{a.version}.json"
        tar.add(manifest_file, arcname=f"{a.version}/manifest.json")
        for f in FILES:
            print(f"adding {f}")
            tar.add(data / f, arcname=f"{a.version}/{f}")
    print(f"{bundle} ({bundle.stat().st_size / 1e6:,.0f} MB), version {a.version}")


if __name__ == "__main__":
    main()
