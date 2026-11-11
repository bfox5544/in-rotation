from conftest import rg_id
from test_accounts import CREDS, account
from test_api import ILLMATIC, LIQUID_SWORDS, MADVILLAINY, TPAB, ids, rate, rated, session
from test_artists import AMNESIAC, OLD_AMNESIAC

KID_A, OK_COMPUTER = rg_id("Kid A"), rg_id("OK Computer")
HIPHOP = {rg_id(t) for t in ("Illmatic", "Madvillainy", "To Pimp a Butterfly", "Liquid Swords", "Untrue")}
ROCK = {rg_id(t) for t in ("OK Computer", "In Rainbows", "Kid A", "Amnesiac", "Dummy", "Discovery")}


def recs(client, h) -> dict:
    return client.get("/api/me/recommendations", headers=h).json()


def test_rate_in_half_stars_change_and_clear(client):
    h = session(client)
    assert rate(client, h, KID_A, 3.5) == 204 and rated(client, h) == {KID_A: 3.5}
    assert rate(client, h, KID_A, 0.5) == 204 and rated(client, h) == {KID_A: 0.5}      # replaces
    for bad in (0, 5.5, 3.25, 6):
        assert rate(client, h, KID_A, bad) == 422
    assert rate(client, h, "nope", 3) == 404
    assert client.delete(f"/api/me/ratings/{KID_A}", headers=h).status_code == 204 and rated(client, h) == {}


def test_ratings_drive_recommendations(client):
    h = session(client)
    for album_id in (ILLMATIC, MADVILLAINY, TPAB):
        rate(client, h, album_id, 4.5)
    body = recs(client, h)
    assert body["source"] == "listening-data" and ids(body["items"])[0] == LIQUID_SWORDS
    assert not {ILLMATIC, MADVILLAINY, TPAB} & set(ids(body["items"]))


def test_below_three_stars_excludes_but_does_not_seed(client):
    h = session(client)
    rate(client, h, OK_COMPUTER, 0.5)
    rate(client, h, KID_A, 2.5)
    body = recs(client, h)
    assert body["source"] == "popularity"                                              # nothing liked yet
    assert not {OK_COMPUTER, KID_A} & set(ids(body["items"]))


def test_stars_steer_the_query(client):
    def top(hiphop_stars: float, rock_stars: float) -> str:
        h = session(client)
        rate(client, h, ILLMATIC, hiphop_stars)
        rate(client, h, KID_A, rock_stars)
        return ids(recs(client, h)["items"])[0]
    assert top(5, 3) in HIPHOP and top(3, 5) in ROCK
    assert top(4.5, 3) in HIPHOP and top(3, 4.5) in ROCK                              # half stars steer too


def test_sign_in_merges_ratings_and_the_accounts_own_win(client):
    first = account(client)                                                             # rated Illmatic 4.5
    other = session(client)
    rate(client, other, ILLMATIC, 1)
    rate(client, other, OK_COMPUTER, 3.5)
    token = client.post("/api/account/login", json=CREDS, headers=other).json()["token"]
    assert rated(client, {"Authorization": f"Bearer {token}"}) == {ILLMATIC: 4.5, OK_COMPUTER: 3.5}
    assert rated(client, first) == {ILLMATIC: 4.5, OK_COMPUTER: 3.5}


def test_ratings_follow_musicbrainz_merges(client):
    h = session(client)
    rate(client, h, OLD_AMNESIAC, 4)
    assert rated(client, h) == {AMNESIAC: 4}
    client.delete(f"/api/me/ratings/{AMNESIAC}", headers=h)
    assert rated(client, h) == {}
