"""The only operations the assistant's model can request (ADR 0014).

Each tool validates its own arguments, acts for the signed-in user only, and returns compact
JSON. Recommendations come from the engine (app/engine.py) with the same settings, exclusions
and artist cap as For you; the model never invents albums, and every album it can show is one
these tools returned. Historical listeners appear only as counts.
"""
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session as Db

from ..catalog import get_catalog
from ..engine import ARTIST_SEEDS, LISTENER_CAPS, get_engine
from ..models import Album
from ..routes import _later, _ratings, _set_item, _list_name, ListName, excluded, liked_seeds, record_impressions
from ..schema import CUSTOM, List, ListItem, User
from .provider import ToolSpec

POPULARITY = ("anything", "less_known", "under_the_radar", "deep_cuts")   # For you depth steps, LISTENER_CAPS order
POOL = 250                    # candidates fetched before genre or year filters
GENRE_SEEDS = 10              # a genre's most-listened albums, added to the query when the filter leaves too few
EXPLORE_GENRES = 3            # unfamiliar genres used for "outside my taste"


class ToolError(Exception):
    """A bad argument or request; the message goes back to the model so it can correct itself."""


@dataclass
class TurnState:
    """What one user message's tool calls share and leave behind."""
    db: Db
    user: User
    shown: list[str]                                         # albums already recommended in this conversation
    cards: dict[str, list[str]] = field(default_factory=dict)   # tool name -> album ids from its last call
    action: dict | None = None                               # the last save, for Undo


def _summary(album: Album) -> dict:
    return {"id": album.id, "title": album.title, "artist": album.artist, "year": album.year,
            "genres": album.genres[:3], "listeners": get_engine().listeners.get(album.id, 0)}


def _int(args: dict, name: str, default: int | None, low: int, high: int) -> int | None:
    value = args.get(name, default)
    if value is None:
        return None
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a whole number")
    if not low <= value <= high:
        raise ToolError(f"{name} must be between {low} and {high}")
    return value


def _ids(args: dict, name: str, most: int) -> list[str]:
    value = args.get(name) or []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ToolError(f"{name} must be a list of ids")
    if len(value) > most:
        raise ToolError(f"{name} takes at most {most} ids")
    return value


def _albums(ids: list[str]) -> list[Album]:
    """Catalog albums for ids from earlier tool results; an unknown id is an error, not a guess."""
    catalog = get_catalog()
    found = catalog.get_many(ids)
    known = {a.id for a in found}
    missing = [i for i, current in zip(ids, catalog.canonical_each(ids)) if current not in known]
    if missing:
        raise ToolError(f"Unknown album ids {missing[:3]}: use ids returned by search_catalog or other tools")
    return found


def _genre(name: str | None) -> str | None:
    if not name:
        return None
    catalog = get_catalog()
    found = catalog.genre(name)
    if found is None:
        raise ToolError(f"No genre called {name!r} in the catalog. Try a broader one, for example: {', '.join(catalog.genres()[:12])}")
    return found


def search_catalog(t: TurnState, args: dict) -> dict:
    query = str(args.get("query", "")).strip()[:100]
    if not query:
        raise ToolError("query is required")
    limit = _int(args, "limit", 5, 1, 10)
    albums, _ = get_catalog().search(query, limit=limit)
    t.cards["search_catalog"] = [a.id for a in albums]
    return {"albums": [_summary(a) for a in albums],
            "artists": get_catalog().search_artists(query, 3)}


def get_album_details(t: TurnState, args: dict) -> dict:
    album = _albums([str(args.get("album_id", ""))])[0]
    tracklist = get_catalog().tracklist(album.id)
    tracks = [tr for d in tracklist.discs for tr in d.tracks] if tracklist else []
    ratings = _ratings(t.db, t.user)
    lists = t.db.execute(select(List.name, List.kind).join(ListItem).where(
        List.user_id == t.user.id, ListItem.album_id.in_(get_catalog().saved_as(album.id)))).all()
    similar = get_catalog().get_many(get_engine().similar(album.id, n=5))
    t.cards["get_album_details"] = [*t.cards.get("get_album_details", []), album.id]
    return {**_summary(album), "all_genres": album.genres,
            "tracks": {"count": len(tracks), "titles": [tr.title for tr in tracks[:25]],
                       "minutes": round(sum(tr.seconds or 0 for tr in tracks) / 60) if tracks and all(tr.seconds for tr in tracks) else None},
            "your_rating": ratings.get(album.id), "on_your_lists": [n if k == CUSTOM else "Listen later" for n, k in lists],
            "listeners_also_love": [{"id": a.id, "title": a.title, "artist": a.artist} for a in similar]}


def taste_profile(t: TurnState, loved: int = 25, liked: int = 25, disliked: int = 15) -> dict:
    """The user's taste from their ratings and lists. Favorites are 4.5-5 stars; dislikes 2 stars or less."""
    ratings = _ratings(t.db, t.user)
    albums = {a.id: a for a in get_catalog().get_many(list(ratings))}
    pick = lambda keep, n: [{"title": albums[a].title, "artist": albums[a].artist, "stars": s}
                            for a, s in sorted(ratings.items(), key=lambda x: -x[1]) if a in albums and keep(s)][:n]
    good = [albums[a] for a, s in ratings.items() if a in albums and s >= 4]
    lists = t.db.execute(select(List.name, List.kind, List.id).where(List.user_id == t.user.id)).all()
    counts = Counter(t.db.scalars(select(ListItem.list_id).where(ListItem.list_id.in_([i for *_, i in lists]))))
    return {"rated_albums": len(ratings),
            "favorites": pick(lambda s: s >= 4.5, loved), "liked": pick(lambda s: 3.5 <= s < 4.5, liked),
            "disliked": pick(lambda s: s <= 2, disliked),
            "top_genres": [g for g, _ in Counter(g for a in good for g in a.genres).most_common(8)],
            "top_artists": [a for a, _ in Counter(a.artist for a in good).most_common(8)],
            "lists": [{"name": "Listen later" if k != CUSTOM else n, "albums": counts[i]} for n, k, i in lists]}


def get_taste_profile(t: TurnState, args: dict) -> dict:
    return taste_profile(t)


def _artist_seeds(artist_ids: list[str]) -> tuple[list[str], set[str], list[str]]:
    """(seed albums, every album by these artists, names) for 'like this artist'."""
    catalog, seeds, own, names = get_catalog(), [], set(), []
    for artist_id in artist_ids:
        artist = catalog.artist(artist_id)
        if artist is None:
            raise ToolError(f"Unknown artist id {artist_id!r}: use ids returned by search_catalog")
        studio, other = catalog.artist_albums(artist_id)
        seeds += [a.id for a in (studio or other)[:ARTIST_SEEDS]]
        own |= {a.id for a in studio + other}
        names.append(artist["name"])
    return seeds, own, names


def recommend_albums(t: TurnState, args: dict) -> dict:
    catalog, engine = get_catalog(), get_engine()
    count = _int(args, "count", 10, 1, 20)
    popularity = args.get("popularity") or "anything"
    if popularity not in POPULARITY:
        raise ToolError(f"popularity must be one of {', '.join(POPULARITY)}")
    cap = LISTENER_CAPS[POPULARITY.index(popularity)]
    genre = _genre(args.get("genre"))
    family = catalog.genre_family(genre) if genre else set()   # the genre and its subgenres
    year_from, year_to = _int(args, "year_from", None, 1900, 2100), _int(args, "year_to", None, 1900, 2100)
    like_albums = [a.id for a in _albums(_ids(args, "like_album_ids", 10))]
    artist_seeds, artist_albums, artist_names = _artist_seeds(_ids(args, "like_artist_ids", 5))
    ratings = _ratings(t.db, t.user)
    exclude = excluded(t.db, t.user, ratings) | set(t.shown) | set(like_albums) | artist_albums
    avoid_genres: set[str] = set()

    if like_albums or artist_seeds:
        seeds: dict[str, float] = {a: 1.0 for a in like_albums + artist_seeds}
        names = [a.title for a in catalog.get_many(like_albums)] + artist_names
        basis = f"listeners who love {', '.join(names)}"
    elif args.get("outside_my_taste"):
        mine = taste_profile(t)["top_genres"][:6]
        avoid_genres = set(mine)
        fresh = [g for g in catalog.genres() if g not in avoid_genres][:EXPLORE_GENRES]
        seeds = {a.id: 1.0 for g in fresh for a in catalog.search("", genre=g, limit=4)[0]}
        basis = f"genres you haven't rated much: {', '.join(fresh)}" + (f" (you mostly rate {', '.join(mine)})" if mine else "")
    else:
        seeds = liked_seeds(ratings)
        basis = "your ratings of 3 stars and up, weighted by stars"

    def keep(album: Album) -> bool:
        return ((genre is None or bool(family & set(album.genres)))
                and (year_from is None or (album.year is not None and album.year >= year_from))
                and (year_to is None or (album.year is not None and album.year <= year_to))
                and not avoid_genres & set(album.genres))

    filtered = genre or year_from or year_to or avoid_genres
    picked = [a for a in catalog.get_many(engine.recommend(seeds, exclude, n=POOL if filtered else count, max_listeners=cap))
              if keep(a)][:count] if seeds else []
    if seeds and genre and len(picked) < count:
        # Too few of the user's matches are in this genre: add the genre's best-known albums to the query.
        extra = {a.id: 1.0 for a in catalog.search("", genre=genre, limit=GENRE_SEEDS)[0] if a.id not in seeds}
        seeds = {**seeds, **extra}
        exclude |= set(extra)
        more = [a for a in catalog.get_many(engine.recommend(seeds, exclude, n=POOL, max_listeners=cap)) if keep(a)]
        picked += [a for a in more if a.id not in {p.id for p in picked}][:count - len(picked)]
        basis += f", plus well-known {genre} albums"
    if not picked:
        if engine._seeds(seeds)[1]:
            return {"basis": basis, "albums": [], "note": "Nothing matched these filters. Suggest loosening them."}
        # Nothing to go on yet (no ratings the engine knows): the most-listened albums, like For you does.
        pool, _ = catalog.search("", genre=genre, limit=POOL)
        picked = [a for a in pool if a.id not in exclude and keep(a)
                  and (cap is None or 10 <= engine.listeners.get(a.id, 0) <= cap)][:count]
        basis, seeds = "the most-listened albums (no ratings to go on yet; suggest rating a few)", {}

    why = engine.explain(seeds, [a.id for a in picked]) if seeds else {}
    seed_albums = {a.id: a for a in catalog.get_many([s for w in why.values() for s, _ in w["seeds"]])}
    out = []
    for rank, album in enumerate(picked, start=1):
        item = {**_summary(album), "rank": rank}
        if w := why.get(album.id):
            item["why"] = {
                "listeners": f"{w['listeners_with_album']} of the {w['listeners']} listeners who have a query album also have it",
                "score": round(w["score"], 4),
                "most_similar_query_albums": [
                    {"title": seed_albums[s].title, "artist": seed_albums[s].artist, "share_of_score": share,
                     **({"your_rating": ratings[s]} if s in ratings else {})}
                    for s, share in w["seeds"] if s in seed_albums]}
        out.append(item)
    t.cards["recommend_albums"] = [a.id for a in picked]
    if why:                                                  # personal picks, not the popularity fallback
        record_impressions(t.db, t.user, [a.id for a in picked], "ask")
    note = {"note": f"Only {len(out)} albums matched."} if len(out) < count else {}
    saved = {}
    if (target := args.get("save_to_list")) and picked:
        # "Make me a playlist of ...": the user asked for a list, so it's made (or added to) in the same step.
        saved = {"saved": _save(t, [a.id for a in picked], target, create=True)}
    return {"basis": basis, "popularity": popularity, "albums": out, **note, **saved}


def compare_listeners(t: TurnState, args: dict) -> dict:
    engine = get_engine()
    albums = _albums(_ids(args, "album_ids", 10))
    if not albums:
        raise ToolError("album_ids needs at least one id")
    ref_album, ref_artist = args.get("reference_album_id"), args.get("reference_artist_id")
    if bool(ref_album) == bool(ref_artist):
        raise ToolError("give exactly one of reference_album_id or reference_artist_id")
    if ref_album:
        ref = _albums([str(ref_album)])[0]
        ref_ids, reference = [ref.id], {"album": ref.title, "artist": ref.artist}
    else:
        _, own, names = _artist_seeds([str(ref_artist)])
        ref_ids, reference = list(own), {"artist": names[0]}
    ref_listeners = engine.listeners_of(ref_ids)
    rows = []
    for album in albums:
        if album.id in ref_ids:       # the reference's own album: overlap would be trivially 100%
            rows.append({"id": album.id, "title": album.title, "artist": album.artist, "is_reference": True})
            continue
        mine = engine.listeners_of([album.id])
        both = int(np.intersect1d(mine, ref_listeners, assume_unique=True).size)
        rows.append({"id": album.id, "title": album.title, "artist": album.artist, "listeners": int(mine.size),
                     "also_have_reference": both, "percent": round(100 * both / mine.size, 1) if mine.size else None})
    t.cards["compare_listeners"] = [a.id for a in albums] + ([ref_ids[0]] if ref_album else [])
    return {"reference": {**reference, "listeners": int(ref_listeners.size)}, "albums": rows,
            "meaning": "listeners = people in the listening data with the album in their top 50; "
                       "also_have_reference = how many of them also have the reference"}


def _save(t: TurnState, album_ids: list[str], list_name: str | None, create: bool) -> dict:
    """Add albums to Listen later (no name) or a custom list, creating it if `create`; records the action for Undo."""
    albums = _albums(album_ids)
    if not albums:
        raise ToolError("album_ids needs at least one id")
    name = " ".join(str(list_name or "").split())
    created = False
    if not name or name.casefold() == "listen later":
        lst = _later(t.db, t.user)
    else:
        lst = t.db.scalar(select(List).where(List.user_id == t.user.id, List.kind == CUSTOM,
                                             List.name.ilike(name.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_"), escape="\\")))
        if lst is None:
            if not create:
                names = list(t.db.scalars(select(List.name).where(List.user_id == t.user.id, List.kind == CUSTOM)))
                raise ToolError(f"No list called {name!r}. Existing lists: {names or 'none'}. Set create_list to make it.")
            try:
                lst = List(user_id=t.user.id, name=_list_name(ListName(name=name[:200])), kind=CUSTOM)
            except HTTPException as e:
                raise ToolError(e.detail)
            t.db.add(lst)
            t.db.flush()
            created = True
    already = set(get_catalog().canonical(list(t.db.scalars(select(ListItem.album_id).where(ListItem.list_id == lst.id)))))
    added = [a.id for a in albums if a.id not in already]
    for album_id in added:
        _set_item(t.db, lst, album_id, True)
    t.db.flush()
    saved_to = "Listen later" if lst.kind != CUSTOM else lst.name
    t.action = {"kind": "saved", "listId": lst.id if lst.kind == CUSTOM else None, "listName": saved_to,
                "albumIds": added, "createdList": created}
    return {"list": saved_to, "added": len(added), "already_there": len(albums) - len(added), "created_list": created}


def save_albums(t: TurnState, args: dict) -> dict:
    ids = _ids(args, "album_ids", 20)
    result = _save(t, ids, args.get("list_name"), bool(args.get("create_list")))
    t.cards["save_albums"] = [a.id for a in _albums(ids)]
    return result


_STR = {"type": "string"}
_IDS = lambda most, what: {"type": "array", "items": _STR, "maxItems": most, "description": what}

TOOLS: dict[str, tuple[ToolSpec, object]] = {spec.name: (spec, fn) for spec, fn in [
    (ToolSpec("search_catalog", "Find albums and artists in the site's catalog by title or artist name (or a genre name). "
              "Use it to get the ids other tools need, e.g. before recommending 'like Radiohead'.",
              {"type": "object", "properties": {
                  "query": {"type": "string", "description": "Album title, artist name or genre"},
                  "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
               "required": ["query"]}), search_catalog),
    (ToolSpec("get_album_details", "Facts about one album: year, genres, track list, listener count, the user's rating "
              "and lists, and albums its listeners also love.",
              {"type": "object", "properties": {"album_id": _STR}, "required": ["album_id"]}), get_album_details),
    (ToolSpec("get_taste_profile", "The user's fuller taste profile: favorites (4.5-5 stars), liked, disliked "
              "(2 stars or less), top genres and artists, and their lists. The prompt already has a short summary.",
              {"type": "object", "properties": {}}), get_taste_profile),
    (ToolSpec("recommend_albums", "Personalized album recommendations from the site's recommendation engine (collaborative "
              "filtering over listening data). The ONLY source of recommendations. Without like_* ids it uses the user's "
              "ratings. Albums the user rated, saved, dismissed or was already shown here are left out. Each result has a "
              "'why' with the evidence for it.",
              {"type": "object", "properties": {
                  "count": {"type": "integer", "minimum": 1, "maximum": 20, "description": "How many (default 10)"},
                  "popularity": {"type": "string", "enum": list(POPULARITY),
                                 "description": "anything = best matches; less_known = under 5,000 listeners; "
                                                "under_the_radar = under 1,000; deep_cuts = under 200 (less mainstream = a later step)"},
                  "genre": {"type": "string", "description": "Keep only albums tagged with this genre, e.g. 'dream pop'"},
                  "year_from": {"type": "integer", "description": "Earliest release year, e.g. 1990 for the 1990s"},
                  "year_to": {"type": "integer", "description": "Latest release year, e.g. 1999"},
                  "like_album_ids": _IDS(10, "Recommend albums like these (ids from other tools) instead of the user's ratings"),
                  "like_artist_ids": _IDS(5, "Recommend albums like these artists' work (ids from search_catalog); their own albums are left out"),
                  "outside_my_taste": {"type": "boolean", "description": "Something different: albums from genres the user rarely rates"},
                  "save_to_list": {"type": "string", "description": "Only when the user asks to make or fill a list or playlist: "
                                   "save every album returned to this list (created if it doesn't exist). Use the name they gave, "
                                   "else a short Title Case name for the request, e.g. '1980s Rock'. 'Listen later' for their Listen later list"}}}),
     recommend_albums),
    (ToolSpec("compare_listeners", "How many listeners of each album also have a reference album or artist, from the listening "
              "data. Use it for 'which of those is most like X' or comparing two albums' audiences.",
              {"type": "object", "properties": {
                  "album_ids": _IDS(10, "Albums to compare"),
                  "reference_album_id": {"type": "string"}, "reference_artist_id": {"type": "string"}},
               "required": ["album_ids"]}), compare_listeners),
    (ToolSpec("save_albums", "Save albums to the user's Listen later list or one of their lists (made if create_list). ONLY when the "
              "user's latest message asks to save, add, or make a list or playlist of albums. 'These' or 'those' means every "
              "album in the latest answer, not only the ones its text named.",
              {"type": "object", "properties": {
                  "album_ids": _IDS(20, "Albums to save"),
                  "list_name": {"type": "string", "description": "A list name; omit for Listen later"},
                  "create_list": {"type": "boolean", "description": "Create the list if it doesn't exist (when the user asks for a list or playlist)"}},
               "required": ["album_ids"]}), save_albums),
]}


def specs() -> list[ToolSpec]:
    return [spec for spec, _ in TOOLS.values()]


def run(t: TurnState, name: str, args: dict) -> dict:
    """Run one tool call; problems go back to the model as {"error": ...} rather than failing the turn."""
    entry = TOOLS.get(name)
    if entry is None:
        return {"error": f"There is no tool called {name!r}"}
    try:
        return entry[1](t, args)
    except ToolError as e:
        return {"error": str(e)}


def cards(t: TurnState, reply: str) -> list[str]:
    """Album ids to show as cards: recommendations first, else saved albums, else albums looked at or
    compared, else search results the reply mentions (all of them if it names none)."""
    for source in ("recommend_albums", "save_albums", "get_album_details", "compare_listeners"):
        if t.cards.get(source):
            return t.cards[source]
    found = t.cards.get("search_catalog", [])
    named = [a.id for a in get_catalog().get_many(found) if a.title.casefold() in reply.casefold()]
    return named or found[:4]
