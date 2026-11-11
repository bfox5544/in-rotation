from conftest import rg_id


def session(client) -> dict[str, str]:
    token = client.post("/api/session").json()["token"]
    return {"Authorization": f"Bearer {token}"}


def titles(resp) -> list[str]:
    return [a["title"] for a in resp.json()["items"]]


def ids(albums) -> list[str]:
    return [a["id"] for a in albums]


def names(albums) -> list[str]:
    return [a["title"] for a in albums]


def rate(client, h, album_id: str, stars: float = 5) -> int:
    return client.put(f"/api/me/ratings/{album_id}", json={"rating": stars}, headers=h).status_code


def rated(client, h) -> dict[str, float]:
    return {r["album"]["id"]: r["rating"] for r in client.get("/api/me/library", headers=h).json()["rated"]}


ILLMATIC, MADVILLAINY, TPAB, LIQUID_SWORDS = (rg_id(t) for t in ("Illmatic", "Madvillainy", "To Pimp a Butterfly", "Liquid Swords"))


def test_catalog_build_matches_names_and_aliases(world):
    r = world["report"]
    assert r["by_method"]["exact"]["albums"] == 16 and r["by_method"]["alias"]["albums"] == 1
    assert r["by_method"]["co-artist"]["albums"] == 1 and r["by_method"]["mbid"]["albums"] == 1
    assert {u["title"] for u in r["top_unmatched"]} == {"Bootleg Tape", "Dark Side of the Moon"}


def test_tied_keys_prefer_the_exact_title(world):
    import sqlite3
    db = sqlite3.connect(world["catalog"])
    album_id = db.execute("SELECT album_id FROM album_id_map m JOIN model_albums USING (model_idx) WHERE title LIKE 'Return%'").fetchone()[0]
    assert album_id == rg_id("Return to the 36 Chambers: The Dirty Version")


def test_mbids_are_validated_against_artist_and_title(world):
    import sqlite3
    db = sqlite3.connect(world["catalog"])
    mapped = dict(db.execute("SELECT artist, album_id FROM album_id_map JOIN model_albums USING (model_idx) "
                             "WHERE artist IN ('Pink Floyd', 'Taylor Swift')").fetchall())
    assert mapped["Pink Floyd"] is None                                     # another artist's album: rejected
    assert mapped["Taylor Swift"] == rg_id("THE TORTURED POETS DEPARTMENT")  # an edition of the album: kept


def test_search_ranks_title_prefix_first(client):
    assert titles(client.get("/api/albums", params={"q": "dis"}))[0] == "Discovery"


def test_search_ignores_accents_and_case(client):
    assert titles(client.get("/api/albums", params={"q": "BEYONCE"})) == ["Lemonade"]


def test_search_finds_artist_and_genre(client):
    assert "Illmatic" in titles(client.get("/api/albums", params={"q": "hip hop"}))
    assert titles(client.get("/api/albums", params={"q": "tame imp"})) == ["Currents"]


def test_search_finds_the_dataset_spelling(client):
    assert titles(client.get("/api/albums", params={"q": "gza genius"})) == ["Liquid Swords"]   # alias only in the dataset


def test_search_handles_symbols_in_genre(client):
    assert set(titles(client.get("/api/albums", params={"q": "r&b"}))) == {"Blonde", "Lemonade"}


def test_genre_filter_paging_and_no_match(client):
    page = client.get("/api/albums", params={"genre": "rock", "limit": 2}).json()
    assert page["total"] == 4 and len(page["items"]) == 2 and all("rock" in a["genres"] for a in page["items"])
    assert client.get("/api/albums", params={"q": "zzzz"}).json() == {"items": [], "total": 0}
    assert "rock" in client.get("/api/genres").json()


def test_album_detail_has_cover_and_listener_based_similar(client):
    body = client.get(f"/api/albums/{rg_id('OK Computer')}").json()
    assert body["album"]["artist"] == "Radiohead" and body["album"]["year"] == 1994
    assert body["album"]["coverUrl"] == f"/api/covers/{rg_id('OK Computer')}"
    similar = names(body["similar"])
    assert "OK Computer" not in similar and "Dummy" in similar
    assert sum(a["artist"] == "Radiohead" for a in body["similar"]) <= 2   # artist cap
    assert client.get("/api/albums/nope").status_code == 404


def test_library_requires_session(client):
    assert client.get("/api/me/library").status_code == 401
    assert client.get("/api/me/library", headers={"Authorization": "Bearer bogus"}).status_code == 401


def test_ratings_and_later_roundtrip(client):
    h = session(client)
    assert rate(client, h, ILLMATIC) == 204 and rate(client, h, ILLMATIC) == 204   # idempotent
    assert client.put(f"/api/me/later/{rg_id('Untrue')}", headers=h).status_code == 204
    lib = client.get("/api/me/library", headers=h).json()
    assert rated(client, h) == {ILLMATIC: 5} and ids(lib["later"]) == [rg_id("Untrue")]
    assert "favorites" not in lib and client.put(f"/api/me/favorites/{ILLMATIC}", headers=h).status_code == 404
    client.delete(f"/api/me/ratings/{ILLMATIC}", headers=h)
    assert rated(client, h) == {}


def test_unknown_album_cannot_be_saved(client):
    h = session(client)
    assert rate(client, h, "nope") == 404 and client.put("/api/me/later/nope", headers=h).status_code == 404


def test_sessions_are_isolated(client):
    a, b = session(client), session(client)
    rate(client, a, rg_id("Blonde"))
    assert rated(client, b) == {}


def test_recommendations_fall_back_to_popularity_without_ratings(client):
    body = client.get("/api/me/recommendations", headers=session(client)).json()
    assert body["source"] == "popularity" and body["items"]


def test_recommendations_come_from_listening_data(client):
    h = session(client)
    for album_id in (ILLMATIC, MADVILLAINY):
        rate(client, h, album_id)
    client.put(f"/api/me/later/{TPAB}", headers=h)
    body = client.get("/api/me/recommendations", headers=h).json()
    got = ids(body["items"])
    assert body["source"] == "listening-data"
    assert got[0] == LIQUID_SWORDS                       # the rest of the hip-hop cluster, merged across aliases
    assert not {ILLMATIC, MADVILLAINY, TPAB} & set(got)  # rated and listen-later excluded
    assert len(got) == len(set(got))                     # GZA and GZA/Genius collapse to one album
    assert "Bootleg Tape" not in names(body["items"])     # unmatched: never shown


def test_recommendations_come_in_pages(client):
    h = session(client)
    rate(client, h, ILLMATIC, 5)
    everything = client.get("/api/me/recommendations", params={"limit": 60}, headers=h).json()
    total = everything["total"]
    assert total == len(everything["items"]) >= 3
    first = client.get("/api/me/recommendations", params={"limit": 2}, headers=h).json()
    second = client.get("/api/me/recommendations", params={"limit": 2, "offset": 2}, headers=h).json()
    assert first["total"] == second["total"] == total
    assert ids(first["items"]) + ids(second["items"]) == ids(everything["items"])[:4]
    assert client.get("/api/me/recommendations", params={"offset": total}, headers=h).json()["items"] == []
    assert client.get("/api/me/recommendations", params={"offset": 241}, headers=h).status_code == 422
    fallback = client.get("/api/me/recommendations", params={"limit": 2, "offset": 2}, headers=session(client)).json()
    assert fallback["source"] == "popularity" and len(fallback["items"]) == 2 and fallback["total"] >= 4


def test_recommendations_say_which_rated_albums_led_to_them(client):
    h = session(client)
    rate(client, h, ILLMATIC, 5)
    rate(client, h, rg_id("Kid A"), 4)
    res = client.get("/api/me/recommendations", headers=h).json()
    assert res["because"], "at least one recommendation is explained"
    shown = set(ids(res["items"]))
    for album_id, seeds in res["because"].items():
        assert album_id in shown and 1 <= len(seeds) <= 2
        assert set(seeds) <= {ILLMATIC, rg_id("Kid A")}
    assert client.get("/api/me/recommendations", headers=session(client)).json()["because"] == {}


def test_recommendations_respect_limit(client):
    h = session(client)
    rate(client, h, rg_id("Kid A"))
    assert len(client.get("/api/me/recommendations", params={"limit": 2}, headers=h).json()["items"]) == 2


def test_depth_keeps_only_albums_under_the_listener_cap(client, monkeypatch):
    import app.routes
    from app.catalog import get_catalog
    listeners = {a.id: get_catalog()._query("SELECT popularity FROM albums WHERE id = ?", (a.id,))[0]["popularity"]
                 for a in get_catalog().popular(50)}
    cap = sorted(listeners.values())[len(listeners) // 2]   # about half the test albums are over it
    monkeypatch.setattr(app.routes, "LISTENER_CAPS", (None, cap, cap, cap))
    h = session(client)
    rate(client, h, rg_id("Kid A"))
    for headers in (h, session(client)):   # listening data, then the popularity fallback
        body = client.get("/api/me/recommendations", params={"depth": 1}, headers=headers).json()
        assert body["items"] and all(listeners[a["id"]] <= cap for a in body["items"])
    everything = ids(client.get("/api/me/recommendations", headers=h).json()["items"])
    assert any(listeners[a] > cap for a in everything)      # depth 0 is uncapped


ELECTRONIC_FAMILY = {"electronic", "house", "trip hop"}


def test_for_you_filters_keep_only_matching_albums(client):
    h = session(client)
    rate(client, h, rg_id("Untrue"))                      # in both the rock and electronic clusters
    unfiltered = client.get("/api/me/recommendations", params={"limit": 60}, headers=h).json()
    assert any(not ELECTRONIC_FAMILY & set(a["genres"]) for a in unfiltered["items"])
    body = client.get("/api/me/recommendations", params={"genre": "Electronic", "limit": 60}, headers=h).json()
    assert body["source"] == "listening-data" and body["items"]
    assert all(ELECTRONIC_FAMILY & set(a["genres"]) for a in body["items"])   # subgenres count (trip hop, house)
    assert body["total"] == len(body["items"])
    years = client.get("/api/me/recommendations", params={"year_from": 2015, "year_to": 2015}, headers=h).json()
    assert [a["title"] for a in years["items"]] == ["Currents"]
    both = client.get("/api/me/recommendations", params={"genre": "rock", "country": "gb", "type": "studio"}, headers=h).json()
    assert both["items"] and all("rock" in a["genres"] and a["country"] == "GB" for a in both["items"])


def test_a_filtered_list_is_the_full_ranking_narrowed(client):
    """Item kNN scores every album, so a filter keeps the order of the albums that pass it (ADR 0026, 0028)."""
    from app.catalog import get_catalog
    from app.engine import get_engine
    client.get("/api/health")
    engine = get_engine()
    only = get_catalog().filtered_ids(genre="electronic")
    full = engine.recommend([rg_id("Untrue")], n=200, artist_cap=None)
    narrowed = engine.recommend([rg_id("Untrue")], n=200, artist_cap=None, only=only)
    assert narrowed and set(narrowed) <= only
    assert narrowed == [a for a in full if a in only][:len(narrowed)]


def test_for_you_filters_say_when_nothing_close_matches(client):
    h = session(client)
    rate(client, h, ILLMATIC)
    body = client.get("/api/me/recommendations", params={"country": "ZZ"}, headers=h).json()
    assert body == {"items": [], "source": "listening-data", "total": 0, "because": {}}


def test_for_you_filters_apply_to_the_popularity_fallback(client):
    body = client.get("/api/me/recommendations", params={"genre": "rock", "limit": 60}, headers=session(client)).json()
    assert body["source"] == "popularity" and body["items"]
    assert all("rock" in a["genres"] for a in body["items"]) and body["total"] == len(body["items"])


def test_for_you_filtered_picks_are_explained(client):
    h = session(client)
    rate(client, h, rg_id("Untrue"))
    rate(client, h, rg_id("Kid A"), 4)
    res = client.get("/api/me/recommendations", params={"genre": "electronic"}, headers=h).json()
    assert res["because"]
    for seeds in res["because"].values():
        assert set(seeds) <= {rg_id("Untrue"), rg_id("Kid A")}


def test_for_you_filters_by_album_length(client):
    # Only Kid A and Dummy have track lists. Kid A's has an untimed track, so it has no length and matches no band.
    timed = {rg_id("Dummy")}
    h = session(client)
    rate(client, h, rg_id("Untrue"))
    short = client.get("/api/me/recommendations", params={"length": "under_30"}, headers=h).json()
    assert short["source"] == "listening-data" and short["items"] and set(ids(short["items"])) <= timed
    assert client.get("/api/me/recommendations", params={"length": "over_60"}, headers=h).json()["total"] == 0
    both = client.get("/api/me/recommendations", params={"length": "under_30", "genre": "trip hop"}, headers=h).json()
    assert names(both["items"]) == ["Dummy"]
    fallback = client.get("/api/me/recommendations", params={"length": "under_30"}, headers=session(client)).json()
    assert fallback["source"] == "popularity" and set(ids(fallback["items"])) == timed
    assert client.get("/api/me/recommendations", params={"length": "forever"}, headers=h).status_code == 422
    assert [b["key"] for b in client.get("/api/browse/options").json()["lengths"]] == ["under_30", "30_45", "45_60", "over_60"]


def test_for_you_filters_are_validated(client):
    h = session(client)
    assert client.get("/api/me/recommendations", params={"type": "vinyl"}, headers=h).status_code == 422
    assert client.get("/api/me/recommendations", params={"country": "GBR"}, headers=h).status_code == 422
    assert client.get("/api/me/recommendations", params={"year_from": 99}, headers=h).status_code == 422


def test_depth_is_validated(client):
    h = session(client)
    assert client.get("/api/me/recommendations", params={"depth": 4}, headers=h).status_code == 422


def test_library_says_when_each_album_was_saved(client):
    h = session(client)
    client.put(f"/api/me/later/{ILLMATIC}", headers=h)
    lst = client.post("/api/me/lists", json={"name": "Mix"}, headers=h).json()
    client.put(f"/api/me/lists/{lst['id']}/albums/{rg_id('Kid A')}", headers=h)
    lib = client.get("/api/me/library", headers=h).json()
    from datetime import datetime
    assert set(lib["laterAdded"]) == {ILLMATIC}
    assert datetime.fromisoformat(lib["laterAdded"][ILLMATIC]).tzinfo is not None
    assert set(lib["lists"][0]["added"]) == {rg_id("Kid A")}


def test_diversify_reorders_for_you_toward_unlike_albums(client):
    """Diversify (ADR 0029): the same kind of picks, re-ranked so each is also unlike the ones before it."""
    import numpy as np
    from app.engine import get_engine
    h = session(client)
    for title in ("OK Computer", "Untrue", "Illmatic"):
        rate(client, h, rg_id(title), 5)
    get = lambda **p: client.get("/api/me/recommendations", params={"limit": 12, **p}, headers=h).json()
    plain, diverse = get(), get(diverse="true")
    assert diverse["source"] == "listening-data" and len(diverse["items"]) == len(plain["items"])
    assert not {rg_id(t) for t in ("OK Computer", "Untrue", "Illmatic")} & {a["id"] for a in diverse["items"]}
    assert diverse["because"]
    engine = get_engine()

    def closeness(items):
        models = [engine.models_of[a["id"]][0] for a in items[:6]]
        sim = engine.model.similarity(models, models)
        return (sim.sum() - np.trace(sim)) / (len(models) * (len(models) - 1))
    assert closeness(diverse["items"]) <= closeness(plain["items"])
    assert client.get("/api/me/recommendations", params={"diverse": "maybe"}, headers=h).status_code == 422
