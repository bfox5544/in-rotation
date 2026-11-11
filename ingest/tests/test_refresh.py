import hashlib
import io
import json
import sqlite3
import tarfile

import pandas as pd
import pytest

from ingest.refresh import refresh

ALBUMS = [("Radiohead", "Kid A"), ("Portishead", "Dummy"), ("Burial", "Untrue"), ("Nas", "Illmatic")]


def rg_doc(i: int, artist: str, title: str) -> dict:
    return {"id": f"rg-{i}", "title": title, "primary-type": "Album", "first-release-date": "2000-01-01",
            "artist-credit": [{"name": artist, "joinphrase": "", "artist": {"id": f"ar-{artist}", "name": artist}}]}


def publish(mirror, folder: str, albums, corrupt: bool = False) -> None:
    """Put a release-group dump and its SHA256SUMS on the fake mirror and point LATEST at it."""
    d = mirror / "json-dumps" / folder
    d.mkdir(parents=True)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:xz") as tar:
        for name, data in [("TIMESTAMP", folder.encode()),
                           ("mbdump/release-group", "".join(json.dumps(rg_doc(i, a, t)) + "\n" for i, (a, t) in albums).encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    (d / "release-group.tar.xz").write_bytes(buf.getvalue())
    digest = "0" * 64 if corrupt else hashlib.sha256(buf.getvalue()).hexdigest()
    (d / "SHA256SUMS").write_text(f"{digest} *release-group.tar.xz\n")
    (mirror / "json-dumps" / "LATEST").write_text(folder + "\n")


@pytest.fixture()
def site(tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    pd.DataFrame({"album_idx": range(len(ALBUMS)), "album_key": [f"{a.lower()} | {t.lower()}" for a, t in ALBUMS],
                  "artist": [a for a, _ in ALBUMS], "title": [t for _, t in ALBUMS], "mbid": None,
                  "n_users": [400, 300, 200, 100], "total_plays": 1}).to_parquet(model / "albums.parquet")
    mirror = tmp_path / "mirror"
    s = {"mb_dir": str(tmp_path / "mb"), "model_dir": str(model), "out": str(tmp_path / "catalog.db"),
         "base": mirror.as_uri(), "log": lambda _: None}
    publish(mirror, "20261028-001001", enumerate(ALBUMS))
    assert refresh(**s)["status"] == "refreshed"     # first build
    return s, mirror, tmp_path


def albums(path) -> int:
    return sqlite3.connect(path).execute("SELECT count(*) FROM albums").fetchone()[0]


def test_refresh_skips_when_up_to_date_and_swaps_a_newer_dump(site):
    s, mirror, tmp = site
    assert refresh(**s) == {"status": "up to date", "dump_dir": "20261028-001001"}
    publish(mirror, "20261101-001001", enumerate(ALBUMS))
    result = refresh(**s)
    assert result["status"] == "refreshed" and result["change"]["retired_albums"] == 0
    assert json.loads((tmp / "mb" / "ingest_meta.json").read_text())["dump_dir"] == "20261101-001001"
    assert (tmp / "catalog.db.prev").exists() and albums(s["out"]) == 4
    assert not (tmp / "mb" / "staging").exists() and not list((tmp / "mb").glob("*.tar.*"))


def test_bad_checksum_leaves_the_live_catalog_alone(site):
    s, mirror, tmp = site
    publish(mirror, "20261101-001001", enumerate(ALBUMS), corrupt=True)
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        refresh(**s)
    assert albums(s["out"]) == 4 and not (tmp / "catalog.db.prev").exists()


def test_a_dump_that_loses_coverage_is_refused_unless_forced(site):
    s, mirror, tmp = site
    publish(mirror, "20261101-001001", enumerate(ALBUMS[1:], start=1))   # Kid A (most listened) is missing
    result = refresh(**s)
    assert result["status"] == "refused" and "listening coverage fell" in result["problems"][0]
    assert albums(s["out"]) == 4                                             # live catalog untouched
    forced = refresh(**s, force=True)
    assert forced["status"] == "refreshed" and forced["change"]["retired_albums"] == 1 and albums(s["out"]) == 3
