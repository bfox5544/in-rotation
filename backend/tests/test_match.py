"""Album-page match scores (ADR 0019), on the small test world."""
from conftest import rg_id
from test_api import ILLMATIC, rate, session

KID_A, OK_COMPUTER, IN_RAINBOWS = rg_id("Kid A"), rg_id("OK Computer"), rg_id("In Rainbows")


def match(client, h, album_id) -> dict:
    r = client.get(f"/api/albums/{album_id}/match", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_no_taste_without_liked_ratings(client):
    h = session(client)
    assert match(client, h, KID_A)["status"] == "no_taste"
    rate(client, h, OK_COMPUTER, 2)                         # under 3 stars: not part of the taste
    assert match(client, h, KID_A)["status"] == "no_taste"


def test_a_score_from_albums_like_yours(client):
    h = session(client)
    rate(client, h, OK_COMPUTER, 5)
    rate(client, h, IN_RAINBOWS, 4.5)
    m = match(client, h, KID_A)
    assert m["status"] == "ok" and 0 <= m["score"] <= 100
    assert 3 <= m["withAlbum"] <= m["listeners"]
    assert {a["id"] for a in m["alongside"]} <= {OK_COMPUTER, IN_RAINBOWS} and m["alongside"]
    other = match(client, h, ILLMATIC)                      # hip hop listeners don't share this taste
    assert other["status"] == "few_listeners" or other["score"] < m["score"]


def test_a_rated_album_is_scored_as_if_it_were_not(client):
    h = session(client)
    rate(client, h, OK_COMPUTER, 5)
    rate(client, h, IN_RAINBOWS, 5)
    before = match(client, h, KID_A)
    rate(client, h, KID_A, 5)
    assert match(client, h, KID_A) == before                # Kid A itself is left out of the query
    rate(client, h, KID_A, 1)
    assert match(client, h, KID_A) == before


def test_albums_outside_the_listening_data_and_unknown_ids(client, monkeypatch):
    from app.engine import get_engine
    h = session(client)
    rate(client, h, OK_COMPUTER, 5)
    monkeypatch.delitem(get_engine().models_of, ILLMATIC)    # as if no listener in the data had it
    assert match(client, h, ILLMATIC) == {"status": "not_in_data", "score": None, "listeners": None,
                                             "withAlbum": None, "alongside": []}
    assert client.get(f"/api/albums/{rg_id('No Such Album')}/match", headers=h).status_code == 404
    assert client.get(f"/api/albums/{KID_A}/match").status_code == 401


def test_every_recommended_album_gets_a_match_score(client):
    """Picks are limited to albums the match score can score (engine.SUPPORTED_ONLY, ADR 0028)."""
    h = session(client)
    rate(client, h, OK_COMPUTER, 5)
    rate(client, h, IN_RAINBOWS, 4)
    picks = client.get("/api/me/recommendations", params={"limit": 24}, headers=h).json()
    assert picks["source"] == "listening-data" and picks["items"]
    for album in picks["items"]:
        m = match(client, h, album["id"])
        assert m["status"] == "ok", (album["title"], m)


def test_a_small_album_needs_support_in_proportion_to_its_own_audience():
    """Run 9: 0.1% of a big audience can exceed a Deep Cut's listeners, so 5% of its own listeners also counts."""
    from app.engine import Engine
    assert Engine._need(100_000, 5_000_000) == 100       # 0.1% of the holders
    assert Engine._need(100_000, 150) == 7.5              # 5% of its own 150 listeners
    assert Engine._need(100_000, 20) == 3                 # never under 3
    assert Engine._need(1_000, 150) == 3
