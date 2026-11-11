import os
import time

import pytest

from conftest import rg_id
from test_artists import AMNESIAC, OLD_AMNESIAC

KID_A, DUMMY = rg_id("Kid A"), rg_id("Dummy")
JPEG = b"\xff\xd8\xff fake jpeg"


@pytest.fixture()
def archive(monkeypatch):
    """A fake Cover Art Archive: Dummy has no art, everything else returns JPEG. Records requests."""
    import app.covers
    calls = []

    async def fake(album_id):
        calls.append(album_id)
        return None if album_id == DUMMY else JPEG
    monkeypatch.setattr(app.covers, "fetch_cover", fake)
    return calls


def test_a_miss_fetches_once_then_serves_from_disk(client, archive):
    first = client.get(f"/api/covers/{KID_A}")
    assert first.status_code == 200 and first.content == JPEG and first.headers["content-type"] == "image/jpeg"
    assert "max-age=2592000" in first.headers["cache-control"]
    again = client.get(f"/api/covers/{KID_A}")
    assert again.status_code == 200 and again.content == JPEG and archive == [KID_A]     # no second fetch
    assert os.path.exists(os.path.join(os.environ["INROTATION_COVERS"], KID_A[:2], f"{KID_A}.jpg"))


def test_missing_art_is_a_remembered_404(client, archive):
    assert client.get(f"/api/covers/{DUMMY}").status_code == 404
    assert client.get(f"/api/covers/{DUMMY}").status_code == 404 and archive == [DUMMY]   # remembered
    marker = os.path.join(os.environ["INROTATION_COVERS"], DUMMY[:2], f"{DUMMY}.none")
    old = time.time() - 8 * 24 * 3600
    os.utime(marker, (old, old))                                                         # past the week
    client.get(f"/api/covers/{DUMMY}")
    assert archive == [DUMMY, DUMMY]


def test_unknown_ids_never_reach_the_archive_and_merged_ids_resolve(client, archive):
    assert client.get("/api/covers/nope").status_code == 404
    assert client.get("/api/covers/00000000-0000-0000-0000-000000000000").status_code == 404
    assert client.get(f"/api/covers/{OLD_AMNESIAC}").status_code == 200 and archive == [AMNESIAC]


def test_archive_failures_are_not_cached(client, monkeypatch):
    import httpx

    import app.covers
    async def down(album_id):
        raise httpx.ConnectTimeout("archive down")
    monkeypatch.setattr(app.covers, "fetch_cover", down)
    r = client.get(f"/api/covers/{KID_A}")
    assert r.status_code == 502 and r.headers["cache-control"] == "no-store"
    assert not os.path.exists(os.path.join(os.environ["INROTATION_COVERS"], KID_A[:2]))
