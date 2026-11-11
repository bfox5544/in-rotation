from datetime import timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session as Db

from recs.ratings import query_weight

from . import auth
from .auth import CurrentUser, OptionalUser, create_anonymous_user
from .catalog import KINDS, LENGTHS, POPULARITY, SORTS, get_catalog
from .db import DB
from .engine import LISTENER_CAPS, get_engine
from .models import Album, Tracklist
from .limits import device_of
from .profiles import MyProfile, ProfileFields, apply_profile, avatar_dir, check_profile, my_profile
from .schema import CUSTOM, LISTEN_LATER, Dismissal, Impression, List, ListItem, Rating, Session, User, now

router = APIRouter(prefix="/api")


class AlbumPage(BaseModel):
    items: list[Album]
    total: int


class AlbumDetail(BaseModel):
    album: Album
    similar: list[Album]
    tracklist: Tracklist | None = None


class AlbumList(BaseModel):
    id: int
    name: str
    albums: list[Album]           # newest first
    added: dict[str, str] = {}    # album id -> ISO time it was added (list sorting)


class RatedAlbum(BaseModel):
    album: Album
    rating: float                 # 0.5-5 in half stars


class Library(BaseModel):
    rated: list[RatedAlbum]       # newest first
    later: list[Album]
    lists: list[AlbumList]
    laterAdded: dict[str, str] = {}   # album id -> ISO time it was saved (the "Listened yet?" prompt)


class Stars(BaseModel):
    rating: float = Field(ge=0.5, le=5, multiple_of=0.5)


class Artist(BaseModel):
    id: str
    name: str


class RelatedArtist(Artist):
    album: Album                  # the album that best represents the overlap


class ArtistPage(BaseModel):
    artist: Artist
    albums: list[Album]           # studio albums
    other: list[Album]            # EPs, singles, live albums, compilations
    related: list[RelatedArtist]


class Me(BaseModel):
    email: str | None
    profile: MyProfile | None = None     # ADR 0018


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class Registration(Credentials, ProfileFields):
    """An account is a profile (ADR 0018): a username and a name come with it; public is opt-in."""


class ListName(BaseModel):
    name: str = Field(max_length=200)


class Recommendations(BaseModel):
    items: list[Album]
    source: str
    total: int                  # recommendations available across all pages (at most MAX_RECOMMENDATIONS)
    because: dict[str, list[str]] = {}   # album id -> up to 2 of the user's rated album ids that best explain it


MAX_RECOMMENDATIONS = 240       # For You pages through this many (10 pages of 24)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/session", status_code=201)
def create_session(db: DB, request: Request) -> dict[str, str]:
    """A new anonymous user. 429 after auth.LIMITS["session"] from one device in an hour."""
    auth.allow(db, "session", device_of(request))
    return {"token": create_anonymous_user(db)}


@router.get("/genres")
def genres() -> list[str]:
    return get_catalog().genres()


Kind = Literal[tuple(KINDS)]                  # type: ignore[valid-type]
Band = Literal[tuple(POPULARITY)]             # type: ignore[valid-type]
Sort = Literal[tuple(SORTS)]                  # type: ignore[valid-type]
Length = Literal[tuple(LENGTHS)]              # type: ignore[valid-type]


class GenreMatch(BaseModel):
    name: str
    albums: int                               # the genre and its subgenres
    parent: str | None                        # its most-listened parent genre, for subgenres


class BrowseOptions(BaseModel):
    decades: list[dict]                       # [{decade, albums}], newest first
    countries: list[dict]                     # [{code, albums}], ISO 3166 codes, most albums first
    types: list[dict]                         # [{key, label, albums}]
    popularity: list[dict]                    # [{key, label, min, max}] listener bands
    sorts: list[str]
    rated: int                                # albums with a MusicBrainz rating
    lengths: list[dict]                       # [{key, label}] album length bands (For You, ADR 0026)


@router.get("/albums", response_model=AlbumPage)
def list_albums(
    q: str = Query("", max_length=100),
    genre: str | None = Query(None, max_length=100),
    limit: int = Query(60, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10_000),
    year_from: int | None = Query(None, ge=1000, le=2100),
    year_to: int | None = Query(None, ge=1000, le=2100),
    artist: str | None = Query(None, max_length=36),
    country: str | None = Query(None, pattern="^[A-Za-z]{2}$"),
    type: Kind | None = None,
    popularity: Band | None = None,
    sort: Sort | None = None,
) -> AlbumPage:
    """Search and browse (ADR 0015). Every filter is optional and they combine; a genre includes its subgenres."""
    catalog = get_catalog()
    items, total = catalog.search(q, catalog.genre(genre) or genre, limit, offset, year_from=year_from, year_to=year_to,
                                  artist=artist, country=country, kind=type, popularity=popularity, sort=sort)
    return AlbumPage(items=items, total=total)


@router.get("/browse/options", response_model=BrowseOptions)
def browse_options() -> BrowseOptions:
    return BrowseOptions(**get_catalog().browse_options())


@router.get("/browse/genres", response_model=list[GenreMatch])
def search_genres(q: str = Query("", max_length=100), limit: int = Query(12, ge=1, le=50)) -> list[GenreMatch]:
    """Genres and subgenres matching the typed words, for the searchable genre filter."""
    return [GenreMatch(**g) for g in get_catalog().search_genres(q, limit)]


@router.get("/albums/{album_id}", response_model=AlbumDetail)
def get_album(album_id: str) -> AlbumDetail:
    catalog = get_catalog()
    album = catalog.get(album_id)
    if album is None:
        raise HTTPException(404, "Album not found")
    return AlbumDetail(album=album, similar=catalog.get_many(get_engine().similar(album_id)),
                       tracklist=catalog.tracklist(album.id))


class Match(BaseModel):
    """GET /albums/{id}/match (ADR 0019). score 0-100 when status is "ok"."""
    status: Literal["ok", "few_listeners", "not_in_data", "no_taste"]
    score: int | None = None
    listeners: int | None = None        # listeners in the data who have one of your albums
    withAlbum: int | None = None        # how many of them also have this album
    alongside: list[Album] = []         # your albums most of its score comes from, largest share first


@router.get("/albums/{album_id}/match", response_model=Match)
def album_match(album_id: str, user: CurrentUser, db: DB) -> Match:
    """How well this album fits your taste, from your ratings of 3 stars and up."""
    _require_album(album_id)
    m = get_engine().match(liked_seeds(_ratings(db, user)), album_id)
    return Match(status=m["status"], score=m.get("score"), listeners=m.get("listeners"), withAlbum=m.get("with_album"),
                 alongside=get_catalog().get_many(m.get("alongside", [])))


@router.get("/artists", response_model=list[Artist])
def search_artists(q: str = Query("", max_length=100), limit: int = Query(6, ge=1, le=24)) -> list[Artist]:
    return [Artist(**a) for a in get_catalog().search_artists(q, limit)]


@router.get("/artists/{artist_id}", response_model=ArtistPage)
def get_artist(artist_id: str) -> ArtistPage:
    catalog = get_catalog()
    artist = catalog.artist(artist_id)
    if artist is None:
        raise HTTPException(404, "Artist not found")
    related = get_engine().related_artists(artist_id)
    names = catalog.artist_names([a for a, _ in related])
    albums = {a.id: a for a in catalog.get_many([album for _, album in related])}
    studio, other = catalog.artist_albums(artist_id)
    return ArtistPage(artist=Artist(**artist), albums=studio, other=other,
                      related=[RelatedArtist(id=a, name=names[a], album=albums[album])
                               for a, album in related if a in names and album in albums])


# --- account -------------------------------------------------------------------------------------

@router.get("/me", response_model=Me)
def me(user: CurrentUser) -> Me:
    return Me(email=user.email, profile=my_profile(user))


@router.post("/account/register", response_model=Me)
def register(body: Registration, user: CurrentUser, db: DB, request: Request) -> Me:
    """Turn the current anonymous session into an account with its profile; the library stays as it is.
    429 after auth.LIMITS["register"] accounts from one device in a day."""
    username, name = check_profile(db, user, body)         # before anything changes
    if user.email is None:                                 # a refusal for an existing account says so (409) instead
        auth.allow(db, "register", device_of(request))
    auth.register(db, user, body.email, body.password)
    apply_profile(user, username, name, body.public)
    return Me(email=user.email, profile=my_profile(user))


@router.post("/account/login")
def login(body: Credentials, request: Request, current: OptionalUser, db: DB) -> dict[str, str]:
    """A new session for the account. An anonymous library in this browser is merged into it.
    429 after 5 failed tries for one email, or 20 from one device, in 15 minutes."""
    account = auth.authenticate(db, body.email, body.password, device_of(request))
    if current is not None and current.email is None:
        auth.merge_into(db, current, account)
    return {"token": auth.new_session(db, account.id)}


class DeleteAccount(BaseModel):
    password: str = Field(max_length=256)


@router.delete("/account", status_code=204)
def delete_account(body: DeleteAccount, request: Request, user: CurrentUser, db: DB) -> Response:
    """Delete the signed-in account and everything in it (ratings, lists, chats, profile, picture). Needs its password.
    Every browser signed in to it starts again with a new, empty library."""
    picture = user.avatar
    auth.delete_account(db, user, body.password, device_of(request))
    if picture:
        (avatar_dir() / picture).unlink(missing_ok=True)
    return Response(status_code=204)


@router.post("/account/logout", status_code=204)
def logout(authorization: Annotated[str, Header()], _: CurrentUser, db: DB) -> Response:
    """End this browser's session. The browser then starts a new, empty anonymous one."""
    db.execute(delete(Session).where(Session.token_hash == auth.hash_token(authorization.partition(" ")[2])))
    return Response(status_code=204)


# --- library -------------------------------------------------------------------------------------

def _item_ids(db: Db, list_id: int) -> list[str]:
    return list(db.scalars(select(ListItem.album_id).where(ListItem.list_id == list_id)
                           .order_by(ListItem.added_at.desc())))


def _later(db: Db, user: User) -> List:
    return db.scalars(select(List).where(List.user_id == user.id, List.kind == LISTEN_LATER)).one()


def _custom_lists(db: Db, user: User) -> list[List]:
    return list(db.scalars(select(List).where(List.user_id == user.id, List.kind == CUSTOM).order_by(List.created_at)))


def _own_list(db: Db, user: User, list_id: int) -> List:
    lst = db.get(List, list_id)
    if lst is None or lst.user_id != user.id or lst.kind != CUSTOM:
        raise HTTPException(404, "List not found")
    return lst


def _albums(ids: list[str]) -> list[Album]:
    return get_catalog().get_many(ids)


def _items(db: Db, list_id: int) -> dict[str, str]:
    """Current album id -> ISO time added, newest first (ids MusicBrainz merged resolve to the current one)."""
    rows = db.execute(select(ListItem.album_id, ListItem.added_at).where(ListItem.list_id == list_id)
                      .order_by(ListItem.added_at.desc())).all()
    out: dict[str, str] = {}
    for (_, at), current in zip(rows, get_catalog().canonical_each([a for a, _ in rows])):
        out.setdefault(current, (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).isoformat())
    return out


def _album_list(db: Db, lst: List) -> AlbumList:
    items = _items(db, lst.id)
    return AlbumList(id=lst.id, name=lst.name, albums=_albums(list(items)), added=items)


def _insert_ignore(db: Db, table, **values) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    db.execute(insert(table).values(**values).on_conflict_do_nothing())


def _require_album(album_id: str) -> str:
    """The album's current id (saved rows always use it); 404 when it is not in the catalog."""
    catalog = get_catalog()
    if not catalog.exists(album_id):
        raise HTTPException(404, "Album not found")
    return catalog.canonical([album_id])[0]


@router.get("/me/library", response_model=Library)
def my_library(user: CurrentUser, db: DB) -> Library:
    later = _items(db, _later(db, user).id)
    return Library(rated=_rated(db, user), later=_albums(list(later)), laterAdded=later,
                   lists=[_album_list(db, lst) for lst in _custom_lists(db, user)])


def _ratings(db: Db, user: User) -> dict[str, float]:
    """Current album id -> stars, newest first. Rows saved under ids MusicBrainz later merged resolve
    to the current id; if two rows land on one album, the newer rating wins."""
    rows = db.execute(select(Rating.album_id, Rating.half_stars).where(Rating.user_id == user.id)
                      .order_by(Rating.updated_at.desc())).all()
    out: dict[str, float] = {}
    for (album_id, half), current in zip(rows, get_catalog().canonical_each([a for a, _ in rows])):
        out.setdefault(current, half / 2)
    return out


def _rated(db: Db, user: User) -> list[RatedAlbum]:
    ratings = _ratings(db, user)
    return [RatedAlbum(album=a, rating=ratings[a.id]) for a in get_catalog().get_many(list(ratings))]


@router.put("/me/ratings/{album_id}", status_code=204)
def rate(album_id: str, body: Stars, user: CurrentUser, db: DB) -> Response:
    current = _require_album(album_id)
    db.execute(delete(Rating).where(Rating.user_id == user.id, Rating.album_id.in_(get_catalog().saved_as(current))))
    db.add(Rating(user_id=user.id, album_id=current, half_stars=round(body.rating * 2)))
    return Response(status_code=204)


@router.delete("/me/ratings/{album_id}", status_code=204)
def unrate(album_id: str, user: CurrentUser, db: DB) -> Response:
    db.execute(delete(Rating).where(Rating.user_id == user.id, Rating.album_id.in_(get_catalog().saved_as(album_id))))
    return Response(status_code=204)


def _set_item(db: Db, lst: List, album_id: str, on: bool) -> Response:
    if on:
        _insert_ignore(db, ListItem, list_id=lst.id, album_id=_require_album(album_id), added_at=now())
    else:
        # Older rows may carry an id MusicBrainz has since merged into this one.
        db.execute(delete(ListItem).where(ListItem.list_id == lst.id, ListItem.album_id.in_(get_catalog().saved_as(album_id))))
    return Response(status_code=204)


@router.put("/me/later/{album_id}", status_code=204)
def add_later(album_id: str, user: CurrentUser, db: DB) -> Response:
    return _set_item(db, _later(db, user), album_id, True)


@router.delete("/me/later/{album_id}", status_code=204)
def remove_later(album_id: str, user: CurrentUser, db: DB) -> Response:
    return _set_item(db, _later(db, user), album_id, False)


def _list_name(body: ListName) -> str:
    name = " ".join(body.name.split())
    if not 1 <= len(name) <= 80:
        raise HTTPException(422, "List names are 1 to 80 characters")
    return name


@router.post("/me/lists", status_code=201, response_model=AlbumList)
def create_list(body: ListName, user: CurrentUser, db: DB) -> AlbumList:
    lst = List(user_id=user.id, name=_list_name(body), kind=CUSTOM)
    db.add(lst)
    db.flush()
    return AlbumList(id=lst.id, name=lst.name, albums=[])


@router.patch("/me/lists/{list_id}", response_model=AlbumList)
def rename_list(list_id: int, body: ListName, user: CurrentUser, db: DB) -> AlbumList:
    lst = _own_list(db, user, list_id)
    lst.name = _list_name(body)
    return _album_list(db, lst)


@router.delete("/me/lists/{list_id}", status_code=204)
def delete_list(list_id: int, user: CurrentUser, db: DB) -> Response:
    db.delete(_own_list(db, user, list_id))
    return Response(status_code=204)


@router.put("/me/lists/{list_id}/albums/{album_id}", status_code=204)
def add_to_list(list_id: int, album_id: str, user: CurrentUser, db: DB) -> Response:
    return _set_item(db, _own_list(db, user, list_id), album_id, True)


@router.delete("/me/lists/{list_id}/albums/{album_id}", status_code=204)
def remove_from_list(list_id: int, album_id: str, user: CurrentUser, db: DB) -> Response:
    return _set_item(db, _own_list(db, user, list_id), album_id, False)


@router.put("/me/dismissed/{album_id}", status_code=204)
def dismiss(album_id: str, user: CurrentUser, db: DB) -> Response:
    """Keep an album off For you. Only an exclusion, never a dislike signal (ADR 0010)."""
    _insert_ignore(db, Dismissal, user_id=user.id, album_id=_require_album(album_id), created_at=now())
    return Response(status_code=204)


@router.delete("/me/dismissed/{album_id}", status_code=204)
def undismiss(album_id: str, user: CurrentUser, db: DB) -> Response:
    db.execute(delete(Dismissal).where(Dismissal.user_id == user.id, Dismissal.album_id.in_(get_catalog().saved_as(album_id))))
    return Response(status_code=204)


def record_impressions(db: Db, user: User, album_ids: list[str], source: str) -> None:
    """Remember albums recommended to the user (first showing only), for Insights (ADR 0017)."""
    for album_id in dict.fromkeys(album_ids):
        _insert_ignore(db, Impression, user_id=user.id, album_id=album_id, source=source, shown_at=now())


def liked_seeds(ratings: dict[str, float]) -> dict[str, float]:
    """The recommendation query: albums rated 3 stars and up, weighted by stars (recs.ratings)."""
    return {a: w for a, stars in ratings.items() if (w := query_weight(stars)) > 0}


def excluded(db: Db, user: User, ratings: dict[str, float]) -> set[str]:
    """Albums never suggested to this user: rated (any stars), on any list, or dismissed."""
    catalog = get_catalog()
    return set(ratings) | set(catalog.canonical(list(db.scalars(
        select(ListItem.album_id).join(List).where(List.user_id == user.id))))) | set(catalog.canonical(list(
        db.scalars(select(Dismissal.album_id).where(Dismissal.user_id == user.id)))))


@router.get("/me/recommendations", response_model=Recommendations)
def my_recommendations(user: CurrentUser, db: DB, limit: Annotated[int, Query(ge=1, le=60)] = 24,
                       depth: Annotated[int, Query(ge=0, le=len(LISTENER_CAPS) - 1)] = 0,
                       offset: Annotated[int, Query(ge=0, le=MAX_RECOMMENDATIONS)] = 0,
                       genre: Annotated[str | None, Query(max_length=100)] = None,
                       year_from: Annotated[int | None, Query(ge=1000, le=2100)] = None,
                       year_to: Annotated[int | None, Query(ge=1000, le=2100)] = None,
                       country: Annotated[str | None, Query(pattern="^[A-Za-z]{2}$")] = None,
                       type: Kind | None = None, length: Length | None = None, diverse: bool = False) -> Recommendations:
    """Rated albums are the query, weighted by stars (recs.ratings: 3 stars and up; below that an
    album only stays out). Nothing rated or listed is ever suggested. With no query album the engine
    knows, the most-listened albums stand in (source "popularity"). Dismissed albums never appear.
    `depth` 1-3 keeps only albums under a listener cap (engine.LISTENER_CAPS; ADR 0012). `offset` pages
    through the ranked list (up to MAX_RECOMMENDATIONS); `total` says how many there are. Only the page
    returned counts as shown (Insights). `because` names, per album, up to two rated albums most of its
    score comes from (engine.explain, ADR 0021). `genre` (with its
    subgenres), `year_from`/`year_to`, `country` and `type` keep only albums passing them, as on Browse
    Albums, and `length` only albums in that length band (catalog.LENGTHS; ADR 0026). `diverse` re-ranks the
    list so each pick is also unlike the ones before it (Diversify, ADR 0029)."""
    catalog = get_catalog()
    cap = LISTENER_CAPS[depth]
    genre = catalog.genre(genre) or genre if genre else None
    filtered = any(v is not None for v in (genre, year_from, year_to, country, type, length))
    only = catalog.filtered_ids(genre, year_from, year_to, country, type, length) if filtered else None
    ratings = _ratings(db, user)
    seeds = liked_seeds(ratings)
    listed = excluded(db, user, ratings)
    ranked = (get_engine().recommend(seeds, exclude=listed, n=MAX_RECOMMENDATIONS, max_listeners=cap, only=only,
                                      diverse=diverse)
              if seeds and only != frozenset() else [])
    if ranked:
        ids = ranked[offset:offset + limit]
        record_impressions(db, user, ids, "for_you")
        why = get_engine().explain(seeds, ids)
        because = {a: w["telling"][:2] for a, w in why.items() if w["telling"]}
        return Recommendations(items=catalog.get_many(ids), source="listening-data", total=len(ranked), because=because)
    if filtered and get_engine().knows(seeds):   # the taste is known, but nothing close to it passes the filters
        return Recommendations(items=[], source="listening-data", total=0)
    if filtered:
        popular = catalog.popular_among(only, MAX_RECOMMENDATIONS, exclude=listed, max_listeners=cap)
    else:
        popular = catalog.popular(MAX_RECOMMENDATIONS, exclude=listed, max_listeners=cap)
    return Recommendations(items=popular[offset:offset + limit], source="popularity", total=len(popular))
