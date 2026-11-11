"""GET /api/albums/{id}/listen/{spotify|apple-music}: open the regular album on a streaming service (ADR 0016).

The catalog keeps up to five MusicBrainz links per album and service (album_links), ranked by how regular
their release looks. That hint is often wrong both ways (a release with bonus tracks still titled "4" on
Spotify; reissues filed under the original), and a quarter of the stored Apple links were dead. So on
first use each candidate is checked against the service's own title for it, through public, keyless
endpoints (Spotify oEmbed, Apple's iTunes lookup): the first one that is the album itself (or a remaster
of it) wins, never a deluxe, expanded, live or other edition (owner request). With none, Apple's search
API is asked for the regular album by the same artist; failing that, the listener lands on the
service's search page. Answers are remembered for a week (a day for a search page).
"""
import logging
import re
import time
from urllib.parse import quote, urlencode

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from .catalog import get_catalog, norm

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

SERVICES = {"spotify": "spotify", "apple-music": "apple_music"}   # URL segment -> album_links.service
TIMEOUT = 4.0
MAX_CHECKS = 4                                       # candidates checked per album and service
FOUND_FOR, SEARCH_FOR = 7 * 86400, 86400             # seconds to remember an answer
_cache: dict[tuple[str, str], tuple[str, float]] = {}   # (album id, service) -> (url, expires)
_APPLE_ID = re.compile(r"music\.apple\.com/(?:([a-z]{2})/)?album/([0-9]+)")
_SINGLE = re.compile(r"\s+- (?:single|ep)$", re.IGNORECASE)          # Apple's suffix for singles and EPs
_TAGS = re.compile(r"\s*[(\[]([^)\]]*)[)\]]")                       # "(Deluxe Edition)", "[2011 Remaster]"
_EDITION_WORDS = r"(?i)deluxe|expanded|anniversary|bonus|collector|limited|special|super|box|demos|outtakes|edition|version|live"


class Unavailable(Exception):
    """The service's API couldn't be asked; nothing is cached so the next click tries again."""


def search_url(service: str, title: str, artist: str) -> str:
    if service == "spotify":
        return f"https://open.spotify.com/search/{quote(f'{title} {artist}')}"
    return f"https://music.apple.com/search?{urlencode({'term': f'{title} {artist}'})}"


def _get(url: str, params: dict) -> httpx.Response:
    """One request to a service's public API (tests replace this)."""
    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        return client.get(url, params=params)


def _title(service: str, url: str) -> str | None:
    """The service's own title for the album a link points to; None if the link is dead."""
    try:
        if service == "spotify":
            r = _get("https://open.spotify.com/oembed", {"url": url})
            if r.status_code in (400, 404) or r.status_code >= 500:   # unknown albums time out (504) on oEmbed
                return None
            r.raise_for_status()
            return r.json().get("title")
        m = _APPLE_ID.search(url)
        if not m:
            return None
        r = _get("https://itunes.apple.com/lookup", {"id": m[2], "entity": "album", "country": m[1] or "us"})
        r.raise_for_status()
        results = r.json().get("results", [])
        return results[0].get("collectionName") if results else None
    except (httpx.HTTPError, ValueError) as e:
        raise Unavailable(e.__class__.__name__) from e


def _same(theirs: str, ours: str) -> bool:
    """Same title, ignoring spacing and punctuation ("40oz. To Freedom"); each "*" stands for one
    censored letter ("Songs About F*****g")."""
    if "*" in theirs:
        pattern = "".join("." if c == "*" else re.escape(c) for c in theirs.casefold())
        return re.fullmatch(pattern, ours.casefold()) is not None
    return norm(theirs).replace(" ", "") == norm(ours).replace(" ", "")


def edition(theirs: str, title: str) -> int | None:
    """How a service's album title relates to ours: 0 the album itself ("Jealous - Single" counts),
    1 a remaster or a mono/stereo mix of it ("... (2011 Remaster)", "Pet Sounds (Original Mono & Stereo
    Mix)"), 2 another edition ("Illmatic (Deluxe Edition)", "... (Live)"),
    None a different title ("Illmatic XX", "OK Computer OKNOTOK 1997 2017")."""
    theirs = _SINGLE.sub("", theirs)
    if _same(theirs, title):
        return 0
    tags = _TAGS.findall(theirs)
    if tags and _same(_TAGS.sub("", theirs), title):
        words = " ".join(tags)
        return 1 if re.search(r"(?i)remaster|\bmono\b|\bstereo\b", words) and not re.search(_EDITION_WORDS, words) else 2
    return None


def _apple_search(title: str, artist: str) -> str | None:
    """The regular album (or a remaster of it) from Apple's search, by the same artist."""
    try:
        r = _get("https://itunes.apple.com/search", {"term": f"{title} {artist}", "entity": "album", "limit": 25, "country": "us"})
        r.raise_for_status()
        results = r.json().get("results", [])
    except (httpx.HTTPError, ValueError) as e:
        raise Unavailable(e.__class__.__name__) from e
    best: tuple[int, int] | None = None
    for i, a in enumerate(results):
        tier, name = edition(a.get("collectionName", ""), title), norm(a.get("artistName", ""))
        if tier is not None and tier < 2 and (name == norm(artist) or norm(artist) in name):
            best = min(best or (tier, i), (tier, i))
    return f"https://music.apple.com/album/{results[best[1]]['collectionId']}" if best else None


def album_url(album_id: str, segment: str) -> str:
    service = SERVICES.get(segment)
    album = get_catalog().get(album_id) if service else None
    if album is None:
        raise HTTPException(404, "Album not found")
    key = (album.id, service)
    hit = _cache.get(key)
    if hit and hit[1] > time.time():
        return hit[0]
    candidates = get_catalog().links(album.id).get(service, [])
    try:
        url, remaster = None, None
        for link, _ in candidates[:MAX_CHECKS]:
            theirs = _title(service, link)
            tier = edition(theirs, album.title) if theirs else None
            if tier == 0:
                url = link
                break
            if tier == 1 and remaster is None:
                remaster = link
        url = url or remaster or (_apple_search(album.title, album.artist) if service == "apple_music" else None)
    except Unavailable as e:
        log.info("%s unavailable (%s); using MusicBrainz's best guess", service, e)
        regular = [link for link, hint in candidates if hint < 2]
        return regular[0] if regular else search_url(service, album.title, album.artist)   # not cached
    _cache[key] = (url or search_url(service, album.title, album.artist), time.time() + (FOUND_FOR if url else SEARCH_FOR))
    return _cache[key][0]


@router.get("/albums/{album_id}/listen/{service}")
def listen(album_id: str, service: str) -> RedirectResponse:
    return RedirectResponse(album_url(album_id, service), status_code=302)
