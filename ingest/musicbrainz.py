"""Parse the MusicBrainz release-group JSON dump into Parquet (M7, pulled ahead of M5).

    python -m ingest.musicbrainz --dump data/musicbrainz/release-group.tar.xz --out data/musicbrainz

Get the dump from https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/<date>/ and
check it against that folder's SHA256SUMS. It is regenerated twice a week; re-running this
script on a newer dump is the refresh path. Bulk data comes from dumps, never the live API.

Outputs in --out:
    release_groups.parquet  rg_mbid, title, primary_type, secondary_types, first_release_date,
                            artist_credit, artist_mbids, genres, rating (0-5), rating_votes
    artists.parquet         artist_mbid, name, sort_name, aliases, genres, country (ISO 3166 code), type
    ingest_meta.json        dump timestamp and counts

Core data is CC0. Genres and tags are listed as supplementary data (CC BY-NC-SA) on the
MusicBrainz licence page: fine for this non-commercial project, review before any other use.
"""
from __future__ import annotations

import argparse
import json
import tarfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

BATCH = 200_000

RG_SCHEMA = pa.schema([
    ("rg_mbid", pa.string()), ("title", pa.string()), ("primary_type", pa.string()),
    ("secondary_types", pa.list_(pa.string())), ("first_release_date", pa.string()),
    ("artist_credit", pa.string()), ("artist_mbids", pa.list_(pa.string())), ("genres", pa.list_(pa.string())),
    ("rating", pa.float32()), ("rating_votes", pa.int32()),
])
ARTIST_SCHEMA = pa.schema([
    ("artist_mbid", pa.string()), ("name", pa.string()), ("sort_name", pa.string()),
    ("aliases", pa.list_(pa.string())), ("genres", pa.list_(pa.string())),
    ("country", pa.string()), ("type", pa.string()),
])


def _top_genres(items: list[dict] | None, n: int = 5) -> list[str]:
    ranked = sorted(items or [], key=lambda g: (-(g.get("count") or 0), g.get("name") or ""))
    return [g["name"] for g in ranked[:n] if g.get("name")]


def parse_release_group(doc: dict) -> tuple[dict, list[dict]]:
    """One dump line -> (release-group row, artist rows)."""
    credit = doc.get("artist-credit") or []
    artists = [c["artist"] for c in credit if c.get("artist")]
    row = {
        "rg_mbid": doc["id"],
        "title": doc.get("title") or "",
        "primary_type": doc.get("primary-type"),
        "secondary_types": doc.get("secondary-types") or [],
        "first_release_date": doc.get("first-release-date") or None,
        "artist_credit": "".join((c.get("name") or "") + (c.get("joinphrase") or "") for c in credit),
        "artist_mbids": [a["id"] for a in artists],
        "genres": _top_genres(doc.get("genres")),
        # MusicBrainz community rating: 0-5 stars from its users' votes (CC0 core data).
        "rating": (doc.get("rating") or {}).get("value"),
        "rating_votes": (doc.get("rating") or {}).get("votes-count") or 0,
    }
    artist_rows = [{
        "artist_mbid": a["id"], "name": a.get("name") or "", "sort_name": a.get("sort-name") or "",
        "aliases": sorted({x["name"] for x in a.get("aliases") or [] if x.get("name")}),
        "genres": _top_genres(a.get("genres")),
        "country": a.get("country") or None,     # where the artist is from, as MusicBrainz records it
        "type": a.get("type"),                   # Person, Group, Orchestra, ...
    } for a in artists]
    return row, artist_rows


def run(dump: str, out_dir: str, log=print) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rg_path, artist_path = out / "release_groups.parquet", out / "artists.parquet"
    rows: list[dict] = []
    artists: dict[str, dict] = {}
    n = 0
    meta: dict = {"dump": Path(dump).name}
    with tarfile.open(dump, mode="r|xz") as tar, pq.ParquetWriter(rg_path, RG_SCHEMA) as writer:
        for member in tar:
            f = tar.extractfile(member) if member.isfile() else None
            if f is None:
                continue
            if member.name == "TIMESTAMP":
                meta["timestamp"] = f.read().decode().strip()
            elif member.name == "mbdump/release-group":
                for line in f:
                    row, artist_rows = parse_release_group(json.loads(line))
                    rows.append(row)
                    for a in artist_rows:
                        artists.setdefault(a["artist_mbid"], a)
                    n += 1
                    if len(rows) >= BATCH:
                        writer.write_table(pa.Table.from_pylist(rows, RG_SCHEMA))
                        rows.clear()
                        log(f"  {n:,} release groups")
        if rows:
            writer.write_table(pa.Table.from_pylist(rows, RG_SCHEMA))
    pq.write_table(pa.Table.from_pylist(list(artists.values()), ARTIST_SCHEMA), artist_path)
    meta.update(release_groups=n, artists=len(artists))
    (out / "ingest_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dump", default="data/musicbrainz/release-group.tar.xz")
    p.add_argument("--out", default="data/musicbrainz")
    a = p.parse_args()
    print(json.dumps(run(a.dump, a.out), indent=2))


if __name__ == "__main__":
    main()
