from sqlalchemy import create_engine, text

from conftest import MERGED, rg_id
from test_api import names, rate, rated, session

RADIOHEAD, AMNESIAC = rg_id("Radiohead"), rg_id("Amnesiac")
OLD_AMNESIAC = next(iter(MERGED))


def test_artist_page_lists_albums_and_related_artists(client):
    body = client.get(f"/api/artists/{RADIOHEAD}").json()
    assert body["artist"] == {"id": RADIOHEAD, "name": "Radiohead"}
    assert set(names(body["albums"])) == {"OK Computer", "In Rainbows", "Kid A", "Amnesiac"} and body["other"] == []
    beyonce = client.get(f"/api/artists/{rg_id('Beyoncé')}").json()
    assert beyonce["albums"] == [] and names(beyonce["other"]) == ["Lemonade"]
    related = body["related"]
    assert related and RADIOHEAD not in [a["id"] for a in related]
    assert len({a["id"] for a in related}) == len(related)              # one album per related artist
    assert "Portishead" in [a["name"] for a in related]                 # same listeners (rock cluster)
    assert client.get("/api/artists/nope").status_code == 404


def test_albums_link_to_their_artist(client):
    album = client.get(f"/api/albums/{rg_id('Her Loss')}").json()["album"]
    assert album["artistId"] == rg_id("Drake")                          # first credited artist


def test_artist_search_uses_names_and_aliases(client):
    assert [a["name"] for a in client.get("/api/artists", params={"q": "radio"}).json()] == ["Radiohead"]
    assert [a["name"] for a in client.get("/api/artists", params={"q": "gza genius"}).json()] == ["GZA"]
    assert client.get("/api/artists", params={"q": ""}).json() == []


def test_ids_merged_by_musicbrainz_keep_working(client, database):
    h = session(client)
    rate(client, h, OLD_AMNESIAC, 4)                                    # saved under the old id: stored as the current one
    assert rated(client, h) == {AMNESIAC: 4}
    assert client.get(f"/api/albums/{OLD_AMNESIAC}").json()["album"]["id"] == AMNESIAC

    # A row saved before the merge still carries the old id.
    user = create_engine(database).connect()
    user.execute(text("UPDATE user_ratings SET album_id = :a"), {"a": OLD_AMNESIAC})
    user.commit()
    user.close()
    assert rated(client, h) == {AMNESIAC: 4}
    rec = client.get("/api/me/recommendations", headers=h).json()
    assert rec["source"] == "listening-data" and AMNESIAC not in [a["id"] for a in rec["items"]]
    client.delete(f"/api/me/ratings/{AMNESIAC}", headers=h)             # removing by the current id clears the old row
    assert rated(client, h) == {}
