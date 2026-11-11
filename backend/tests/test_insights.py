"""The Insights tab's profile (ADR 0017), on the small test world."""
from conftest import rg_id
from test_accounts import CREDS, account
from test_api import ILLMATIC, LIQUID_SWORDS, MADVILLAINY, TPAB, ids, rate, session

KID_A, OK_COMPUTER, KIND_OF_BLUE = rg_id("Kid A"), rg_id("OK Computer"), rg_id("Kind of Blue")


def insights(client, h) -> dict:
    r = client.get("/api/me/insights", headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_an_empty_profile(client):
    data = insights(client, session(client))
    assert data["overview"]["albumsRated"] == 0 and data["overview"]["averageRating"] is None
    assert data["genres"] == [] and data["years"] == [] and data["mainstream"] is None
    assert [r["albums"] for r in data["ratings"]] == [0] * 10
    assert data["recommendations"] == {"shown": 0, "forYou": 0, "ask": 0, "rated": 0, "liked": 0, "saved": 0,
                                       "dismissed": 0, "since": None}


def test_overview_genres_artists_eras_and_ratings(client):
    h = session(client)
    for album_id, stars in ((OK_COMPUTER, 5), (KID_A, 4.5), (ILLMATIC, 4), (KIND_OF_BLUE, 2.5)):
        rate(client, h, album_id, stars)
    client.put(f"/api/me/later/{MADVILLAINY}", headers=h)
    lst = client.post("/api/me/lists", json={"name": "Night"}, headers=h).json()
    client.put(f"/api/me/lists/{lst['id']}/albums/{KID_A}", headers=h)        # saves don't count toward the profile
    data = insights(client, h)
    o = data["overview"]
    assert (o["albumsRated"], o["artistsExplored"], o["genresExplored"] > 0) == (4, 3, True)        # Radiohead, Nas, Miles Davis
    assert "albumsSaved" not in o and "lists" not in o
    assert o["averageRating"] == 4.0
    genres = {g["name"]: g for g in data["genres"]}
    assert genres["rock"]["albums"] == 2 and genres["rock"]["share"] == 0.5 and genres["rock"]["averageRating"] == 4.75
    assert data["genres"][0]["name"] == "rock"                                 # Madvillainy (only saved) adds no hip hop
    radiohead = data["topArtists"][0]
    assert radiohead["name"] == "Radiohead" and radiohead["albums"] == 2 and radiohead["album"]["id"] == OK_COMPUTER
    assert data["favoriteArtists"][0]["name"] == "Radiohead" and data["favoriteArtists"][-1]["name"] == "Miles Davis"
    assert {e["decade"]: e["albums"] for e in data["decades"]} == {1950: 1, 1990: 3}     # the saved Madvillainy left out
    assert data["years"][0] == {"year": 1959, "albums": 1} and data["years"][-1]["year"] == 1994
    assert {r["stars"]: r["albums"] for r in data["ratings"] if r["albums"]} == {2.5: 1, 4.0: 1, 4.5: 1, 5.0: 1}
    assert [a["album"]["id"] for a in data["topAlbums"]] == [OK_COMPUTER, KID_A, ILLMATIC, KIND_OF_BLUE]
    recent = data["recentAlbums"]
    assert recent[0]["album"]["id"] == KIND_OF_BLUE and MADVILLAINY not in [r["album"]["id"] for r in recent]
    assert all(r["rating"] is not None and "action" not in r for r in recent)
    assert len(data["newArtists"]) == 3 and data["mainstream"]["band"] == "Deep Cuts"   # the test world is tiny


def test_recommendation_stats_count_what_happened_after_a_recommendation(client):
    h = session(client)
    rate(client, h, ILLMATIC, 5)                                               # before anything was recommended
    recs = ids(client.get("/api/me/recommendations", params={"limit": 3}, headers=h).json()["items"])
    assert LIQUID_SWORDS in recs and ILLMATIC not in recs
    rate(client, h, recs[0], 4.5)                                              # liked
    rate(client, h, recs[1], 3)                                                # rated, not liked
    client.put(f"/api/me/later/{recs[1]}", headers=h)                          # saved
    client.put(f"/api/me/dismissed/{recs[2]}", headers=h)                     # dismissed
    stats = insights(client, h)["recommendations"]
    assert {k: stats[k] for k in ("shown", "forYou", "ask", "rated", "liked", "saved", "dismissed")} == \
        {"shown": 3, "forYou": 3, "ask": 0, "rated": 2, "liked": 1, "saved": 1, "dismissed": 1}
    client.get("/api/me/recommendations", params={"limit": 3}, headers=h)      # showing again doesn't recount
    assert insights(client, h)["recommendations"]["shown"] <= 5


def test_sign_in_keeps_the_recommendation_history(client):
    account(client)
    other = session(client)
    rate(client, other, TPAB, 5)
    client.get("/api/me/recommendations", params={"limit": 2}, headers=other)
    token = client.post("/api/account/login", json=CREDS, headers=other).json()["token"]
    stats = insights(client, {"Authorization": f"Bearer {token}"})["recommendations"]
    assert stats["shown"] == 2 and stats["forYou"] == 2


def test_insights_are_private(client):
    a, b = session(client), session(client)
    rate(client, a, KID_A, 5)
    assert insights(client, b)["overview"]["albumsRated"] == 0
    assert client.get("/api/me/insights").status_code == 401


from test_chat import ask, fake, liked_hip_hop   # noqa: E402,F401  (the scripted-model fixture)


def test_assistant_recommendations_count_too(client, fake):
    h = liked_hip_hop(client)
    fake.calls = [("recommend_albums", {"count": 2})]
    ask(client, h, "two albums please")
    shown = len(fake.results[0]["albums"])                                     # the tiny world may have fewer than 2
    stats = insights(client, h)["recommendations"]
    assert shown > 0 and stats["ask"] == shown and stats["shown"] == shown
