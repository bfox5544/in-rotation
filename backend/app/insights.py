"""GET /api/me/insights: a music profile from what the user did on the site (ADR 0017).

The profile is built from the user's ratings only (owner request 2026-11-03): saved albums (listen
later and lists) don't count toward genres, artists, eras or discoveries. Artists are the first credited
artist. Recommendation stats (private) count what happened after an album was first recommended,
including saves.

A public profile (ADR 0018) is the same profile without the recommendation stats.
"""
from collections import Counter, defaultdict
from datetime import datetime
from statistics import mean, median

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from .auth import CurrentUser
from .catalog import POPULARITY, get_catalog
from .db import DB
from .engine import get_engine
from .models import Album
from .schema import Dismissal, Impression, List, ListItem, Rating, User

router = APIRouter(prefix="/api")

TOP = 8
GENRES_PER_ALBUM = 3        # an album's leading genres count toward the profile
LIKED = 4.0                 # stars from which a recommended album counts as liked


class Overview(BaseModel):
    albumsRated: int
    artistsExplored: int        # first-credited artists across rated albums
    genresExplored: int
    averageRating: float | None
    memberSince: datetime


class Share(BaseModel):
    name: str
    albums: int
    share: float                # of rated albums
    averageRating: float | None


class ArtistStat(BaseModel):
    id: str | None
    name: str
    albums: int
    averageRating: float | None
    album: Album                # their best-rated (else first) album, for artwork


class Era(BaseModel):
    decade: int
    albums: int
    averageRating: float | None


class YearCount(BaseModel):
    year: int
    albums: int


class StarCount(BaseModel):
    stars: float
    albums: int


class RatedAlbum(BaseModel):
    album: Album
    rating: float


class Discovery(BaseModel):
    album: Album
    at: datetime
    rating: float


class NewArtist(BaseModel):
    id: str | None
    name: str
    at: datetime
    album: Album


class Mainstream(BaseModel):
    medianListeners: int
    band: str                   # the browse popularity band the median falls in


class RecommendationStats(BaseModel):
    shown: int
    forYou: int
    ask: int
    rated: int                  # rated after being recommended
    liked: int                  # rated LIKED stars or more
    saved: int                  # put on listen later or a list
    dismissed: int
    since: datetime | None


class Insights(BaseModel):
    overview: Overview
    genres: list[Share]
    favoriteArtists: list[ArtistStat]     # highest average rating
    topArtists: list[ArtistStat]          # most albums rated
    decades: list[Era]
    years: list[YearCount]                # every year from the earliest to the latest rated
    ratings: list[StarCount]              # 0.5 to 5 in half stars
    topAlbums: list[RatedAlbum]
    recentAlbums: list[Discovery]
    newArtists: list[NewArtist]
    mainstream: Mainstream | None
    recommendations: RecommendationStats | None   # None on a public profile


def _band(listeners: int) -> str:
    for label, lo, hi in POPULARITY.values():
        if (lo is None or listeners >= lo) and (hi is None or listeners <= hi):
            return label
    return "Deep Cuts"


def _avg(values: list[float]) -> float | None:
    return round(mean(values), 2) if values else None


@router.get("/me/insights", response_model=Insights)
def insights(user: CurrentUser, db: DB) -> Insights:
    return build(db, user)


def build(db: Db, user: User, *, public: bool = False) -> Insights:
    """The profile, from ratings only; public=True leaves out the recommendation stats."""
    catalog = get_catalog()
    current = lambda ids: catalog.canonical_each(list(ids))

    # Ratings, newest kept when two rows land on one album (as in the library).
    rows = db.execute(select(Rating.album_id, Rating.half_stars, Rating.updated_at).where(Rating.user_id == user.id)
                      .order_by(Rating.updated_at.desc())).all()
    rated: dict[str, tuple[float, datetime]] = {}
    for (_, half, at), album_id in zip(rows, current(r[0] for r in rows)):
        rated.setdefault(album_id, (half / 2, at))
    collected = catalog.get_many(list(rated))       # the rated albums the catalog still has
    stars = lambda a: rated[a.id][0] if a.id in rated else None
    first_seen = {a.id: rated[a.id][1] for a in collected}

    # Genres, artists, eras
    genre_albums: dict[str, list[Album]] = defaultdict(list)
    for a in collected:
        for g in a.genres[:GENRES_PER_ALBUM]:
            genre_albums[g].append(a)
    genres = sorted(genre_albums.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    names = catalog.artist_names([a.artistId for a in collected if a.artistId])
    by_artist: dict[str, list[Album]] = defaultdict(list)
    for a in collected:
        by_artist[a.artistId or a.artist].append(a)

    def artist(key: str, items: list[Album]) -> ArtistStat:
        scored = [s for a in items if (s := stars(a)) is not None]
        best = max(items, key=lambda a: (stars(a) or 0, -first_seen[a.id].timestamp()))
        return ArtistStat(id=key if key in names else None, name=names.get(key, items[0].artist), albums=len(items),
                          averageRating=_avg(scored), album=best)

    artists = [artist(k, v) for k, v in by_artist.items()]
    favorite = sorted((a for a in artists if a.averageRating is not None),
                      key=lambda a: (-a.averageRating, -a.albums, a.name.casefold()))[:6]
    top = sorted(artists, key=lambda a: (-a.albums, -(a.averageRating or 0), a.name.casefold()))[:TOP]
    dated = [a for a in collected if a.year]
    eras = defaultdict(list)
    for a in dated:
        eras[a.year // 10 * 10].append(a)
    year_counts = Counter(a.year for a in dated)
    years = [YearCount(year=y, albums=year_counts.get(y, 0)) for y in range(min(year_counts), max(year_counts) + 1)] if year_counts else []

    # Ratings
    values = [s for s, _ in rated.values()]
    distribution = Counter(values)
    top_albums = sorted((a for a in collected if a.id in rated), key=lambda a: (-rated[a.id][0], -rated[a.id][1].timestamp()))[:10]

    # Discoveries: the latest albums rated, and artists by when the user first rated one
    events = sorted(((rated[a.id][1], a) for a in collected), key=lambda e: e[0], reverse=True)
    met: dict[str, tuple[datetime, Album]] = {}
    for a in collected:
        key = a.artistId or a.artist
        if key not in met or first_seen[a.id] < met[key][0]:
            met[key] = (first_seen[a.id], a)
    new_artists = sorted(met.items(), key=lambda kv: kv[1][0], reverse=True)[:TOP]

    engine_listeners = get_engine().listeners
    listeners = [n for a in collected if a.id in rated and (n := engine_listeners.get(a.id)) is not None]

    rec = None if public else _recommendation_stats(db, user, rated)

    return Insights(
        overview=Overview(albumsRated=len(rated), artistsExplored=len(by_artist),
                          genresExplored=len(genre_albums), averageRating=_avg(values),
                          memberSince=user.created_at),
        genres=[Share(name=g, albums=len(items), share=round(len(items) / len(collected), 3),
                      averageRating=_avg([s for a in items if (s := stars(a)) is not None])) for g, items in genres[:TOP]],
        favoriteArtists=favorite, topArtists=top,
        decades=[Era(decade=d, albums=len(items), averageRating=_avg([s for a in items if (s := stars(a)) is not None]))
                 for d, items in sorted(eras.items())],
        years=years,
        ratings=[StarCount(stars=h / 2, albums=distribution.get(h / 2, 0)) for h in range(1, 11)],
        topAlbums=[RatedAlbum(album=a, rating=rated[a.id][0]) for a in top_albums],
        recentAlbums=[Discovery(album=a, at=at, rating=rated[a.id][0]) for at, a in events[:10]],
        newArtists=[NewArtist(id=k if k in names else None, name=names.get(k, a.artist), at=at, album=a) for k, (at, a) in new_artists],
        mainstream=Mainstream(medianListeners=int(median(listeners)), band=_band(int(median(listeners)))) if listeners else None,
        recommendations=rec)


def _recommendation_stats(db: Db, user: User, rated: dict[str, tuple[float, datetime]]) -> RecommendationStats:
    """What happened after an album was first recommended: rated, liked, saved (listen later or a list), dismissed."""
    current = lambda ids: get_catalog().canonical_each(list(ids))
    saved_rows = db.execute(select(ListItem.album_id, ListItem.added_at).join(List).where(List.user_id == user.id)).all()
    saved: dict[str, datetime] = {}
    for (_, at), album_id in zip(saved_rows, current(r[0] for r in saved_rows)):
        saved[album_id] = min(at, saved.get(album_id, at))
    shown = db.execute(select(Impression.album_id, Impression.source, Impression.shown_at).where(Impression.user_id == user.id)).all()
    dismissal_rows = db.execute(select(Dismissal.album_id, Dismissal.created_at).where(Dismissal.user_id == user.id)).all()
    dismissed = dict(zip(current(r[0] for r in dismissal_rows), (r[1] for r in dismissal_rows)))
    after = lambda moment, start: moment is not None and moment >= start
    return RecommendationStats(
        shown=len(shown), forYou=sum(s == "for_you" for _, s, _ in shown), ask=sum(s == "ask" for _, s, _ in shown),
        rated=sum(after(rated.get(a, (None, None))[1], t) for a, _, t in shown),
        liked=sum(after(rated.get(a, (None, None))[1], t) and rated[a][0] >= LIKED for a, _, t in shown),
        saved=sum(after(saved.get(a), t) for a, _, t in shown),
        dismissed=sum(after(dismissed.get(a), t) for a, _, t in shown),
        since=min((t for _, _, t in shown), default=None))
