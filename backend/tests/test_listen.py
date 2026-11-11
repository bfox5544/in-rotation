"""The streaming redirects (ADR 0016): candidates are checked against the service's own title, other
editions are never used, and no test calls Spotify or Apple for real."""
import httpx
import pytest

from conftest import rg_id

from app import listen

KID_A, DUMMY, ILLMATIC, OK_COMPUTER = rg_id("Kid A"), rg_id("Dummy"), rg_id("Illmatic"), rg_id("OK Computer")


@pytest.fixture()
def services(monkeypatch):
    """Scripted APIs. titles: what each service calls the album at a URL or Apple id (missing = dead);
    results: Apple search results; fail: every request errors."""
    state = {"titles": {"https://open.spotify.com/album/kidaChosen": "Kid A", "777": "Kid A"},
             "results": [], "calls": [], "fail": False}

    def fake(url, params):
        state["calls"].append((url, params))
        req = httpx.Request("GET", url)
        if state["fail"]:
            raise httpx.ConnectError("down")
        if "oembed" in url:
            title = state["titles"].get(params["url"])
            return httpx.Response(200, json={"title": title}, request=req) if title else httpx.Response(504, request=req)
        if url.endswith("lookup"):
            title = state["titles"].get(params["id"])
            return httpx.Response(200, json={"results": [{"collectionName": title}] if title else []}, request=req)
        return httpx.Response(200, json={"results": state["results"]}, request=req)
    monkeypatch.setattr(listen, "_get", fake)
    listen._cache.clear()
    yield state
    listen._cache.clear()


def go(client, album_id, service):
    r = client.get(f"/api/albums/{album_id}/listen/{service}", follow_redirects=False)
    return r.status_code, r.headers.get("location")


def test_a_regular_link_is_used_and_remembered(client, services):
    assert go(client, KID_A, "spotify") == (302, "https://open.spotify.com/album/kidaChosen")
    assert go(client, KID_A, "spotify") == (302, "https://open.spotify.com/album/kidaChosen")
    assert go(client, KID_A, "apple-music") == (302, "https://music.apple.com/album/777")
    assert len(services["calls"]) == 2                                      # the repeat click is cached


def test_a_link_to_another_edition_is_skipped_for_the_next_candidate(client, services):
    services["titles"]["https://open.spotify.com/album/kidaChosen"] = "Kid A (Deluxe Edition)"
    services["titles"]["https://open.spotify.com/album/kidaOlder"] = "Kid A"   # hinted deluxe, but it is the album
    assert go(client, KID_A, "spotify") == (302, "https://open.spotify.com/album/kidaOlder")


def test_a_reissue_with_its_own_title_is_never_used(client, services):
    services["titles"]["https://open.spotify.com/album/oknotok"] = "OK Computer OKNOTOK 1997 2017"
    status, url = go(client, OK_COMPUTER, "spotify")
    assert status == 302 and url.startswith("https://open.spotify.com/search/OK%20Computer")


def test_dead_apple_links_fall_back_to_a_regular_search_result(client, services):
    services["results"] = [
        {"collectionName": "Dummy (Live Tribute)", "artistName": "Someone Else", "collectionId": 1},
        {"collectionName": "Dummy (Deluxe Edition)", "artistName": "Portishead", "collectionId": 41},
        {"collectionName": "Dummy (2014 Remaster)", "artistName": "Portishead", "collectionId": 42},
    ]
    assert go(client, DUMMY, "apple-music") == (302, "https://music.apple.com/album/42")   # the remaster, never the deluxe
    lookup = next(p for u, p in services["calls"] if u.endswith("lookup"))
    assert lookup["country"] == "jp"                                        # the Japanese link checked in its own store


def test_only_other_editions_means_the_search_page(client, services):
    services["results"] = [{"collectionName": "Illmatic (Deluxe Edition)", "artistName": "Nas", "collectionId": 7}]
    assert go(client, ILLMATIC, "apple-music")[1].startswith("https://music.apple.com/search?term=Illmatic+Nas")
    assert go(client, ILLMATIC, "spotify")[1] == "https://open.spotify.com/search/Illmatic%20Nas"


def test_when_a_service_is_down_musicbrainz_regular_guess_is_used_without_caching(client, services):
    services["fail"] = True
    assert go(client, KID_A, "spotify") == (302, "https://open.spotify.com/album/kidaChosen")
    assert go(client, OK_COMPUTER, "spotify")[1].startswith("https://open.spotify.com/search/")   # only a hinted reissue
    assert listen._cache == {}
    assert client.get("/api/albums/nope/listen/spotify", follow_redirects=False).status_code == 404
    assert client.get(f"/api/albums/{KID_A}/listen/tidal", follow_redirects=False).status_code == 404


def test_editions_are_told_apart():
    assert listen.edition("Songs About F*****g", "Songs About Fucking") == 0       # censored
    assert listen.edition("Songs About F*****g", "Songs About Fighting") is None
    assert listen.edition("Jealous - Single", "Jealous") == 0
    assert listen.edition("40oz. To Freedom", "40 oz. to Freedom") == 0
    assert listen.edition("E=MC2", "E=MC²") == 0
    assert listen.edition("Abbey Road (2019 Remaster)", "Abbey Road") == 1
    assert listen.edition("Pet Sounds (Original Mono & Stereo Mix)", "Pet Sounds") == 1
    assert listen.edition("Pet Sounds (50th Anniversary Edition)", "Pet Sounds") == 2
    assert listen.edition("Illmatic (Deluxe Edition)", "Illmatic") == 2
    assert listen.edition("Unplugged (Live)", "Unplugged") == 2
    assert listen.edition("Illmatic XX", "Illmatic") is None
    assert listen.edition("Fearless (Taylor's Version)", "Fearless (Taylor's Version)") == 0
