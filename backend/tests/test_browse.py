"""Browse filters and sorting on /api/albums, and the options behind them (ADR 0015)."""
from conftest import rg_id

from test_api import ids, names

RADIOHEAD = rg_id("Radiohead")


def browse(client, **params) -> list[str]:
    r = client.get("/api/albums", params=params)
    assert r.status_code == 200, r.text
    return names(r.json()["items"])


def test_a_genre_includes_its_subgenres_and_fusions(client):
    electronic = browse(client, genre="electronic")
    assert {"Discovery", "Untrue", "Dummy"} <= set(electronic)          # Dummy is only tagged trip hop
    assert "Dummy" in browse(client, genre="Trip-Hop") and "Discovery" not in browse(client, genre="trip hop")
    assert "To Pimp a Butterfly" in browse(client, genre="jazz")         # jazz rap is a fusion of jazz
    assert "OK Computer" not in browse(client, genre="jazz")             # "influenced by" doesn't count
    assert browse(client, genre="polka") == []


def test_genre_search_mixes_genres_and_subgenres(client):
    find = lambda q: client.get("/api/browse/genres", params={"q": q}).json()
    assert [g["name"] for g in find("hop")] == ["hip hop", "trip hop"]          # word prefixes, most listened first
    trip = find("trip")[0]
    assert trip == {"name": "trip hop", "albums": 1, "parent": "electronic"}
    electronic = find("electronic")[0]                                              # counts its whole family
    assert electronic["parent"] is None
    assert electronic["albums"] == client.get("/api/albums", params={"genre": "electronic"}).json()["total"]
    assert find("jazz")[0]["name"] == "jazz" and find("polka") == []            # exact name first
    assert [g["name"] for g in find("r&b")] == ["r&b"] and find("jazz rap")[0]["name"] == "jazz rap"
    assert len(find("")) == 10 and len(client.get("/api/browse/genres", params={"limit": 3}).json()) == 3   # all 10 genres with albums


def test_options(client):
    o = client.get("/api/browse/options").json()
    assert {c["code"]: c["albums"] for c in o["countries"]}["GB"] == 6     # 4 Radiohead albums, Dummy, Untrue
    assert [d["decade"] for d in o["decades"]][:3] == [2010, 2000, 1990]
    assert {t["key"]: t["albums"] for t in o["types"]}["soundtrack"] == 1
    assert o["rated"] == 5 and "rated" in o["sorts"] and "relevance" not in o["sorts"]


def test_year_artist_country_type_and_popularity_filters(client):
    assert browse(client, year_from=1950, year_to=1969) == ["Kind of Blue"]
    assert set(browse(client, year_from=2000)) == {"Currents", "In Rainbows"}
    assert set(browse(client, artist=RADIOHEAD)) == {"OK Computer", "In Rainbows", "Kid A", "Amnesiac"}
    assert set(browse(client, country="gb", type="studio")) >= {"Untrue", "Dummy", "Kid A"}
    assert "Discovery" not in browse(client, country="GB") and browse(client, country="FR") == ["Discovery"]
    assert browse(client, type="soundtrack") == ["Lemonade"] and "Lemonade" not in browse(client, type="studio")
    assert browse(client, popularity="hits") == [] and len(browse(client, popularity="deep_cuts")) == client.get("/api/albums").json()["total"]
    assert set(browse(client, genre="rock", artist=RADIOHEAD, year_from=2000)) == {"In Rainbows"}


def test_sorting(client):
    assert browse(client, sort="newest")[:2] == ["Currents", "In Rainbows"]
    assert browse(client, sort="oldest")[0] == "Kind of Blue"
    # Ratings shrink toward the mean (4.06 here): 40 votes at 4.5 beat a single 5-star vote, which still
    # edges out 12 votes at 4.2; unrated albums come last
    assert browse(client, sort="rated")[:5] == ["Kind of Blue", "OK Computer", "Untrue", "Illmatic", "Her Loss"]
    title = browse(client, sort="title")
    assert title == sorted(title, key=str.casefold)
    assert browse(client, q="radiohead", sort="newest")[:2] == ["In Rainbows", "Kid A"]
    first = client.get("/api/albums", params={"sort": "rated", "limit": 1}).json()["items"][0]
    assert first["rating"] == 4.6 and first["ratingVotes"] == 30 and first["country"] is None


def test_bad_filters_are_rejected(client):
    for params in ({"type": "bootleg"}, {"popularity": "viral"}, {"sort": "random"}, {"country": "GBR"}, {"year_from": 99}):
        assert client.get("/api/albums", params=params).status_code == 422, params


def test_large_genre_families_give_the_same_results(client, monkeypatch):
    queries = [{"genre": "electronic"}, {"genre": "jazz", "sort": "rated"}, {"genre": "rock", "country": "GB", "sort": "newest"}]
    before = [(browse(client, **q), client.get("/api/albums", params=q).json()["total"]) for q in queries]
    monkeypatch.setattr("app.catalog.LARGE_FAMILY", 0)                   # every family takes the EXISTS path
    assert [(browse(client, **q), client.get("/api/albums", params=q).json()["total"]) for q in queries] == before
