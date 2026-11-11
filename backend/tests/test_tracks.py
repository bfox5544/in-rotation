from conftest import rg_id


def album(client, title: str) -> dict:
    return client.get(f"/api/albums/{rg_id(title)}").json()


def test_track_list_comes_from_the_most_common_edition(client):
    tracklist = album(client, "Kid A")["tracklist"]
    assert tracklist["releaseId"] == rg_id("Kid A release 4")   # 3 tracks like the digital one; the deluxe has 4
    [disc] = tracklist["discs"]                                  # the DVD is left out
    assert [t["title"] for t in disc["tracks"]] == ["Everything in Its Right Place", "Kid A", "The National Anthem"]
    assert disc["format"] == "CD" and disc["title"] is None
    assert [t["seconds"] for t in disc["tracks"]] == [251, None, 240]
    assert [t["artist"] for t in disc["tracks"]] == [None, None, "Portishead"]   # only credits that differ


def test_unofficial_release_is_used_when_there_is_no_other(client):
    [disc] = album(client, "Dummy")["tracklist"]["discs"]
    assert [t["number"] for t in disc["tracks"]] == ["1", "2"] and disc["format"] is None


def test_albums_without_a_track_list(client):
    assert album(client, "Illmatic")["tracklist"] is None


def test_streaming_link_candidates_are_ranked_regular_first(client):
    from app.catalog import get_catalog
    links = get_catalog().links
    kid_a = links(rg_id("Kid A"))
    # The regular release the track list uses (4) beats the deluxe one (3: a bonus track), whose link is
    # still kept as a candidate; the query string is dropped. A US-store Apple link beats a UK one and
    # loses its country, so it opens in the listener's own store.
    assert kid_a["spotify"] == [("https://open.spotify.com/album/kidaChosen", 0), ("https://open.spotify.com/album/kidaOlder", 2)]
    assert kid_a["apple_music"][0] == ("https://music.apple.com/album/777", 0)
    assert kid_a["apple_music"][1] == ("https://music.apple.com/gb/album/1097862870", 0)   # a UK-only id keeps its country
    # Only a Japanese-store link: it keeps the country, since the album may not exist in other stores.
    assert links(rg_id("Dummy")) == {"spotify": [("https://open.spotify.com/album/dummyAlbum", 0)],
                                     "apple_music": [("https://music.apple.com/jp/album/555", 0)]}
    # A reissue with another title ("OKNOTOK") is only a candidate, hinted as another edition.
    assert links(rg_id("OK Computer")) == {"spotify": [("https://open.spotify.com/album/oknotok", 2)]}
    assert links(rg_id("Illmatic")) == {}
