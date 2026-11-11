"""The Album Map (ADR 0022): the offline build on the test world, and the two API routes."""
import json
import os
from pathlib import Path

import numpy as np

from conftest import MERGED, rg_id
from ingest.album_map import build

def members(genre: dict) -> list[int]:
    """Positions from the gap encoding: -1 + steps[0], + steps[1], ..."""
    out, at = [], -1
    for step in genre["steps"]:
        at += step
        out.append(at)
    return out


HIPHOP = ["Illmatic", "Madvillainy", "To Pimp a Butterfly", "Liquid Swords"]
ROCK = ["OK Computer", "In Rainbows", "Kid A", "Amnesiac"]


def session(client) -> dict[str, str]:
    return {"Authorization": f"Bearer {client.post('/api/session').json()['token']}"}


def built(world) -> dict:
    build(world["catalog"], world["model_dir"], Path(os.environ["INROTATION_MAP"]), genre_min=2, log=lambda _: None)
    return json.loads(Path(os.environ["INROTATION_MAP"]).read_text())


def test_map_says_how_to_build_it_until_it_exists(client):
    r = client.get("/api/map")
    assert r.status_code == 404 and "python -m ingest.album_map" in r.json()["detail"]


def test_albums_listened_to_together_sit_together(client, world):
    built(world)
    r = client.get("/api/map")
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip" and "max-age" in r.headers["cache-control"]
    body = r.json()
    albums = body["albums"]
    at = {t: np.array([x, y]) for t, x, y in zip(albums["title"], albums["x"], albums["y"])}
    assert set(HIPHOP + ROCK) <= set(at) and "Bootleg Tape" not in at          # unmatched model albums never show
    assert all(0 <= v <= 1000 for v in albums["x"] + albums["y"])
    assert albums["id"][albums["title"].index("Illmatic")] == rg_id("Illmatic") and all(albums["listeners"])

    def mean_gap(a, b):
        return np.mean([np.linalg.norm(at[x] - at[y]) for x in a for y in b if x != y])
    assert mean_gap(HIPHOP, HIPHOP) < mean_gap(HIPHOP, ROCK)

    hiphop = next(g for g in body["genres"] if g["name"] == "hip hop")
    assert {albums["title"][i] for i in members(hiphop)} >= set(HIPHOP)
    assert all({"kind", "name", "x", "y", "tier"} <= set(label) for label in body["labels"])
    again = client.get("/api/map", headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


def test_map_resolves_merged_albums_and_drops_missing_ones(client, world):
    doc = built(world)
    old_amnesiac = next(old for old, title in MERGED.items() if title == "Amnesiac")
    i = doc["albums"].index(rg_id("Amnesiac"))
    doc["albums"][i] = old_amnesiac                                    # saved under the id MusicBrainz merged away
    doc["albums"][0] = "00000000-0000-0000-0000-000000000000"           # gone from the catalog
    doc["genres"] = {"test": [0, i]}
    Path(os.environ["INROTATION_MAP"]).write_text(json.dumps(doc))
    body = client.get("/api/map").json()
    ids = body["albums"]["id"]
    assert rg_id("Amnesiac") in ids and old_amnesiac not in ids and len(ids) == len(doc["albums"]) - 1
    assert [(g["name"], members(g)) for g in body["genres"]] == [("test", [ids.index(rg_id("Amnesiac"))])]


def test_my_map_marks_for_you_picks_without_counting_them_as_shown(client):
    h = session(client)
    assert client.get("/api/me/map", headers=h).json() == {"recommended": []}   # nothing rated yet
    for title in ("Illmatic", "Madvillainy"):
        client.put(f"/api/me/ratings/{rg_id(title)}", json={"rating": 5}, headers=h)
    picks = client.get("/api/me/map", headers=h).json()["recommended"]
    assert picks and rg_id("Illmatic") not in picks and rg_id("Liquid Swords") in picks
    assert client.get("/api/me/insights", headers=h).json()["recommendations"]["shown"] == 0
    assert client.get("/api/me/map").status_code == 401
