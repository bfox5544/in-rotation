"""Album catalog: MusicBrainz release groups matched to the recommendation model.

Built offline by `python -m ingest.catalog` into a standalone SQLite file, opened read-only
here. Album ids are release-group MBIDs. The catalog stays separate from the model; the
album_id_map table joins the two (see app/engine.py). It stays in SQLite (ADR 0006).

When MusicBrainz merges release groups, the old MBID becomes a redirect (album_redirects).
Saved user rows keep whatever id they were saved under; every lookup here resolves redirects,
so those rows keep working after a refresh (ADR 0007).
"""
import json
import os
import re
import sqlite3
import threading
import unicodedata
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

from .models import Album, Disc, Track, Tracklist

REPO = Path(__file__).resolve().parents[2]
BUILD_HINT = "Build it from the repo root with: python -m ingest.catalog (see README, 'Build the catalog')."
SCHEMA_VERSION = "7"   # must match ingest.catalog.SCHEMA_VERSION


def catalog_path() -> str:
    return os.environ.get("INROTATION_CATALOG", str(REPO / "data" / "catalog.db"))


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w]+", " ", text.casefold()).replace("_", " ").strip()


def compact(text: str) -> str:
    return norm(text).replace(" ", "")


COLUMNS = "id, title, artist, primary_artist_id, year, genres, mbid, cover_url, country, rating, rating_votes"

# Browse filters (ADR 0015). Album types as SQL over primary and secondary types.
KINDS = {
    "studio": ("Studio Albums", "a.primary_type = 'Album' AND a.secondary_types = '[]'"),
    "ep": ("EPs", "a.primary_type = 'EP'"),
    "single": ("Singles", "a.primary_type = 'Single'"),
    "live": ("Live Albums", "a.secondary_types LIKE '%\"Live\"%'"),
    "compilation": ("Compilations", "a.secondary_types LIKE '%\"Compilation\"%'"),
    "soundtrack": ("Soundtracks", "a.secondary_types LIKE '%\"Soundtrack\"%'"),
    "remix": ("Remix Albums", "a.secondary_types LIKE '%\"Remix\"%'"),
    "mixtape": ("Mixtapes", "a.secondary_types LIKE '%\"Mixtape/Street\"%'"),
}
# Listener bands (people in the listening data with the album in their top 50), widest first.
POPULARITY = {
    "hits": ("Hits", 20_000, None),
    "popular": ("Popular", 5_000, 19_999),
    "less_known": ("Less Known", 1_000, 4_999),
    "under_the_radar": ("Under the Radar", 200, 999),
    "deep_cuts": ("Deep Cuts", None, 199),
}
# A genre family this big is filtered by walking albums in sort order and checking album_family for
# each (EXISTS), which stops after a page; smaller ones collect their albums first (IN). Rock's 140K
# albums page in about 1 ms the first way and 80 ms the second (ADR 0015).
# Album length bands for For You (ADR 0026), in minutes: (label, from, under). An album's length is its
# track list's (ADR 0013); albums with an untimed track (about 5%) have no length and match no band.
LENGTHS = {
    "under_30": ("Under 30 Minutes", None, 30),
    "30_45": ("30 to 45 Minutes", 30, 45),
    "45_60": ("45 to 60 Minutes", 45, 60),
    "over_60": ("Over an Hour", 60, None),
}
LARGE_FAMILY = 20_000
FILTERED_CACHE = 16   # filter combinations whose album ids are kept for For You (filtered_ids)
# Each ORDER BY matches an index in ingest.catalog's SCHEMA exactly; change both together. DESC puts
# NULL dates and ratings last.
SORTS = {   # "relevance" exists only with a text query
    "relevance": None,
    "popular": "a.popularity DESC, a.title_norm",
    "newest": "a.release_date DESC, a.popularity DESC",
    "oldest": "a.release_date IS NULL, a.release_date, a.popularity DESC",
    "rated": "a.rating_score DESC, a.rating_votes DESC, a.popularity DESC",
    "title": "a.title_norm, a.popularity DESC",
}


def _album(row: sqlite3.Row) -> Album:
    # Covers go through the API's local cache (app/covers.py, ADR 0011), not straight to the archive.
    return Album(id=row["id"], title=row["title"], artist=row["artist"], artistId=row["primary_artist_id"], year=row["year"],
                 genres=json.loads(row["genres"]), mbid=row["mbid"], coverUrl=f"/api/covers/{row['id']}",
                 country=row["country"], rating=row["rating"], ratingVotes=row["rating_votes"])


def _match(q: str) -> str | None:
    """FTS5 query for word prefixes: 'tame imp' -> '"tame"* AND "imp"*'."""
    tokens = norm(q).split()
    return " AND ".join(f'"{t}"*' for t in tokens) if tokens else None


class Catalog:
    def __init__(self, path: str) -> None:
        if not Path(path).exists():
            raise RuntimeError(f"Catalog not found at {path}. {BUILD_HINT}")
        self.path = path
        self._conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()   # one shared read-only connection; sqlite3 objects aren't thread-safe
        if self.meta("schema_version") != SCHEMA_VERSION:
            raise RuntimeError(f"Catalog at {path} is from an older build. {BUILD_HINT}")
        self._genres = [r["name"] for r in self._query("SELECT name FROM genres ORDER BY listeners DESC LIMIT 24")]
        self._genre_compact = {compact(g): g for g in self._query_col("SELECT name FROM genres")}
        self._options: dict | None = None
        self._genre_list: list[dict] | None = None
        self._filtered: OrderedDict[tuple, frozenset[str]] = OrderedDict()
        self._length_bands: dict[str, frozenset[str]] | None = None
        self._length_lock = threading.Lock()

    def warm_lengths(self) -> None:
        """Work out album lengths in a background thread (about 9 s on the full catalog), so the first
        request with a length filter doesn't wait for them."""
        threading.Thread(target=self.length_bands, name="album-lengths", daemon=True).start()

    def length_bands(self) -> dict[str, frozenset[str]]:
        """{LENGTHS key: album ids in that band}. Summed from the track lists once, then kept (~30 MB).
        Its own connection, so the shared one isn't held for the whole sum."""
        with self._length_lock:
            if self._length_bands is None:
                conn = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
                try:
                    rows = conn.execute(
                        """SELECT album_id, sum(json_extract(t.value, '$[3]')) / 60000.0
                           FROM album_tracks a, json_each(a.media) m, json_each(m.value, '$.tracks') t
                           GROUP BY album_id HAVING count(json_extract(t.value, '$[3]')) = count(*)""").fetchall()
                finally:
                    conn.close()
                self._length_bands = {
                    key: frozenset(a for a, minutes in rows if (lo is None or minutes >= lo) and (hi is None or minutes < hi))
                    for key, (_, lo, hi) in LENGTHS.items()}
            return self._length_bands

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def _query_col(self, sql: str, params: tuple = ()) -> list:
        return [r[0] for r in self._query(sql, params)]

    def meta(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM catalog_meta WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def genres(self) -> list[str]:
        """The most-listened genres, for the Discover filter chips."""
        return self._genres

    def canonical(self, ids: list[str]) -> list[str]:
        """Current ids, in order: redirected ids replaced, duplicates dropped. Unknown ids pass through."""
        if not ids:
            return []
        moved = dict(self._query(f"SELECT old_id, album_id FROM album_redirects WHERE old_id IN ({','.join('?' * len(ids))})",
                                 tuple(ids)))
        return list(dict.fromkeys(moved.get(i, i) for i in ids))

    def canonical_each(self, ids: list[str]) -> list[str]:
        """Like canonical, but one output per input (duplicates kept), for zipping with rows."""
        moved = dict(self._query(f"SELECT old_id, album_id FROM album_redirects WHERE old_id IN ({','.join('?' * len(ids))})",
                                 tuple(ids))) if ids else {}
        return [moved.get(i, i) for i in ids]

    def saved_as(self, album_id: str) -> list[str]:
        """Every id a saved row for this album may carry: the current id and the ids merged into it."""
        current = self.canonical([album_id])[0]
        return [current, *self._query_col("SELECT old_id FROM album_redirects WHERE album_id = ?", (current,))]

    def get(self, album_id: str) -> Album | None:
        found = self.get_many([album_id])
        return found[0] if found else None

    def tracklist(self, album_id: str) -> Tracklist | None:
        """One release's tracks for the album (ADR 0013); None when MusicBrainz has none listed."""
        rows = self._query("SELECT release_id, media FROM album_tracks WHERE album_id = ?", (self.canonical([album_id])[0],))
        if not rows:
            return None
        discs = [Disc(position=m["position"], format=m["format"], title=m["title"],
                      tracks=[Track(number=n or str(i), title=t, artist=a, seconds=round(ms / 1000) if ms else None)
                              for i, (n, t, a, ms) in enumerate(m["tracks"], start=1)])
                 for m in json.loads(rows[0]["media"])]
        return Tracklist(releaseId=rows[0]["release_id"], discs=discs)

    def links(self, album_id: str) -> dict[str, list[tuple[str, int]]]:
        """{service: [(album URL, edition hint), ...] best first} for Spotify and Apple Music, from
        MusicBrainz (ADR 0016). Hint: 0 the regular album, 1 a remaster, 2 another edition."""
        out: dict[str, list[tuple[str, int]]] = {}
        for r in self._query("SELECT service, url, edition FROM album_links WHERE album_id = ? ORDER BY service, rank",
                             (self.canonical([album_id])[0],)):
            out.setdefault(r["service"], []).append((r["url"], r["edition"]))
        return out

    def exists(self, album_id: str) -> bool:
        return bool(self._query("SELECT 1 FROM albums WHERE id = ?", (self.canonical([album_id])[0],)))

    def get_many(self, ids: list[str]) -> list[Album]:
        """Albums in the order of `ids` (redirects resolved, duplicates dropped); unknown ids are skipped."""
        ids = self.canonical(ids)
        if not ids:
            return []
        found = {r["id"]: _album(r) for r in self._query(
            f"SELECT {COLUMNS} FROM albums WHERE id IN ({','.join('?' * len(ids))})", tuple(ids))}
        return [found[i] for i in ids if i in found]

    def artist(self, artist_id: str) -> dict | None:
        rows = self._query("SELECT id, name FROM artists WHERE id = ?", (artist_id,))
        return dict(rows[0]) if rows else None

    def artist_albums(self, artist_id: str) -> tuple[list[Album], list[Album]]:
        """Catalog albums crediting the artist, most-listened first: (studio albums, everything else:
        EPs, singles, live albums, compilations)."""
        rows = self._query(
            f"""SELECT {COLUMNS}, primary_type = 'Album' AND secondary_types = '[]' AS studio FROM albums
                WHERE id IN (SELECT album_id FROM album_artists WHERE artist_id = ?) ORDER BY popularity DESC, year""",
            (artist_id,))
        return [_album(r) for r in rows if r["studio"]], [_album(r) for r in rows if not r["studio"]]

    def artist_names(self, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        return dict(self._query(f"SELECT id, name FROM artists WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)))

    def search_artists(self, q: str, limit: int = 6) -> list[dict]:
        """Artists whose name or an alias matches every word prefix, most-listened first."""
        match = _match(q)
        if not match:
            return []
        return [dict(r) for r in self._query(
            """SELECT a.id, a.name FROM artists a WHERE a.id IN (SELECT artist_id FROM artist_search WHERE artist_search MATCH ?)
               ORDER BY a.popularity DESC LIMIT ?""", (match, limit))]

    def popular(self, limit: int, exclude: set[str] = frozenset(), max_listeners: int | None = None) -> list[Album]:
        rows = self._query(f"SELECT {COLUMNS} FROM albums WHERE popularity <= ? ORDER BY popularity DESC LIMIT ?",
                           (max_listeners if max_listeners is not None else 2**62, limit + len(exclude)))
        return [_album(r) for r in rows if r["id"] not in exclude][:limit]

    def genre(self, name: str | None) -> str | None:
        """The catalog's spelling of a genre ("Hip-Hop" -> "hip hop"), or None if it isn't one."""
        return self._genre_compact.get(compact(name)) if name else None

    def genre_family(self, genre: str) -> set[str]:
        """The genre and all its subgenres (genre_tree)."""
        return set(self._query_col("SELECT genre FROM genre_tree WHERE ancestor = ?", (genre,))) | {genre}

    def search_genres(self, q: str = "", limit: int = 12) -> list[dict]:
        """Genres and subgenres in one list, for the genre filter: [{name, albums, parent}]. Every word of
        `q` must start a word of the name ("hop" finds "hip hop", "trip" finds "trip hop"), and several
        words must appear together; an exact name comes first, then the rest by listeners. `albums` counts the genre's
        whole family; `parent` is its most-listened parent genre, if any. Empty `q`: the biggest genres."""
        if self._genre_list is None:
            self._genre_list = [dict(r) | {"norm": norm(r["name"])} for r in self._query(
                """SELECT g.name, g.albums_all AS albums, g.listeners_all AS listeners,
                          (SELECT p.parent FROM genre_parents p JOIN genres pg ON pg.name = p.parent
                           WHERE p.genre = g.name ORDER BY pg.listeners_all DESC LIMIT 1) AS parent
                   FROM genres g WHERE g.albums_all > 0 ORDER BY g.listeners_all DESC""")]
        tokens, phrase, joined = norm(q).split(), norm(q), compact(q)
        found = [g for g in self._genre_list
                 if all(any(word.startswith(t) for word in g["norm"].split()) for t in tokens)
                 and (len(tokens) < 2 or joined in g["norm"].replace(" ", ""))]   # "r&b" isn't "blues rock"
        found.sort(key=lambda g: g["norm"] != phrase)   # exact name first; stable, so listeners order otherwise
        return [{"name": g["name"], "albums": g["albums"], "parent": g["parent"]} for g in found[:limit]]

    def browse_options(self) -> dict:
        """What the browse filters can offer, with album counts. Computed once (the catalog is read-only)."""
        if self._options is None:
            decades = self._query("SELECT year / 10 * 10 AS decade, count(*) AS albums FROM albums WHERE year IS NOT NULL GROUP BY 1 ORDER BY 1 DESC")
            countries = self._query("SELECT country AS code, count(*) AS albums FROM albums WHERE country IS NOT NULL GROUP BY 1 ORDER BY 2 DESC")
            self._options = {
                "decades": [dict(r) for r in decades],
                "countries": [dict(r) for r in countries],
                "types": [{"key": k, "label": label, "albums": self._query(f"SELECT count(*) FROM albums a WHERE {sql}")[0][0]}
                          for k, (label, sql) in KINDS.items()],
                "popularity": [{"key": k, "label": label, "min": lo, "max": hi} for k, (label, lo, hi) in POPULARITY.items()],
                "sorts": [k for k in SORTS if k != "relevance"],
                "rated": self._query("SELECT count(*) FROM albums WHERE rating_votes > 0")[0][0],
                "lengths": [{"key": k, "label": label} for k, (label, _, _) in LENGTHS.items()],
            }
        return self._options

    def filtered_ids(self, genre: str | None = None, year_from: int | None = None, year_to: int | None = None,
                     country: str | None = None, kind: str | None = None, length: str | None = None) -> frozenset[str]:
        """Every album id passing these browse filters (a genre includes its subgenres) and length band
        (LENGTHS), for narrowing For You (ADR 0026). Rock's family is about 140K ids; the last
        FILTERED_CACHE answers are kept."""
        key = (genre, year_from, year_to, country.upper() if country else None, kind, length)
        with self._lock:
            if key in self._filtered:
                self._filtered.move_to_end(key)
                return self._filtered[key]
        if length is not None:
            band = self.length_bands()[length]
            others = (genre, year_from, year_to, country, kind)
            ids = band & self.filtered_ids(*others) if any(v is not None for v in others) else band
        else:
            ids = self._filter_query(genre, year_from, year_to, country, kind)
        with self._lock:
            self._filtered[key] = ids
            while len(self._filtered) > FILTERED_CACHE:
                self._filtered.popitem(last=False)
        return ids

    def popular_among(self, only: frozenset[str], limit: int, exclude: set[str] = frozenset(),
                      max_listeners: int | None = None) -> list[Album]:
        """The most-listened albums in `only`, best first: For You's fallback with filters (ADR 0026).
        Walks the popularity order in chunks until it has enough."""
        out: list[Album] = []
        offset, chunk = 0, 5000
        while len(out) < limit:
            rows = self._query(f"SELECT {COLUMNS} FROM albums WHERE popularity <= ? ORDER BY popularity DESC LIMIT ? OFFSET ?",
                               (max_listeners if max_listeners is not None else 2**62, chunk, offset))
            out += [_album(r) for r in rows if r["id"] in only and r["id"] not in exclude]
            if len(rows) < chunk:
                break
            offset += chunk
        return out[:limit]

    def _filter_query(self, genre, year_from, year_to, country, kind) -> frozenset[str]:
        where, params = [], []
        if genre:
            where.append("a.rowid IN (SELECT album_rowid FROM album_family WHERE ancestor = ?)")
            params.append(genre)
        if year_from is not None:
            where.append("a.year >= ?")
            params.append(year_from)
        if year_to is not None:
            where.append("a.year <= ?")
            params.append(year_to)
        if country:
            where.append("a.country = ?")
            params.append(country.upper())
        if kind:
            where.append(KINDS[kind][1])
        return frozenset(self._query_col(f"SELECT a.id FROM albums a {'WHERE ' + ' AND '.join(where) if where else ''}",
                                         tuple(params)))

    def search(self, q: str = "", genre: str | None = None, limit: int = 60, offset: int = 0, *,
               year_from: int | None = None, year_to: int | None = None, artist: str | None = None,
               country: str | None = None, kind: str | None = None, popularity: str | None = None,
               sort: str | None = None) -> tuple[list[Album], int]:
        """Accent- and case-insensitive word-prefix search plus browse filters (ADR 0015). A genre
        includes its subgenres. With a text query, title matches rank first, then artist matches, then
        the rest (sort "relevance", the default); otherwise the default is most popular. A query naming
        a genre ("r&b") lists that genre."""
        tokens = norm(q).split()
        where, params = [], []
        counted: list[str] = []    # the count query's version of `where`, where it differs
        query_genre = self.genre(q) if q and not genre else None     # a genre filter wins over a genre-named query
        for g in (genre, query_genre):
            if g:
                collect = "a.rowid IN (SELECT album_rowid FROM album_family WHERE ancestor = ?)"
                big = self._query("SELECT albums_all FROM genres WHERE name = ?", (g,))
                where.append(collect if not big or big[0][0] < LARGE_FAMILY else
                             "EXISTS (SELECT 1 FROM album_family f WHERE f.ancestor = ? AND f.album_rowid = a.rowid)")
                counted.append(collect)
                params.append(g)
        if tokens and not query_genre:
            where.append("a.id IN (SELECT album_id FROM album_search WHERE album_search MATCH ?)")
            params.append(_match(q))
        if year_from is not None:
            where.append("a.year >= ?")
            params.append(year_from)
        if year_to is not None:
            where.append("a.year <= ?")
            params.append(year_to)
        if artist:
            where.append("a.id IN (SELECT album_id FROM album_artists WHERE artist_id = ?)")
            params.append(artist)
        if country:
            where.append("a.country = ?")
            params.append(country.upper())
        if kind:
            where.append(KINDS[kind][1])
        if popularity:
            _, lo, hi = POPULARITY[popularity]
            if lo is not None:
                where.append("a.popularity >= ?")
                params.append(lo)
            if hi is not None:
                where.append("a.popularity <= ?")
                params.append(hi)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        count_clause = f"WHERE {' AND '.join(counted + where[len(counted):])}" if where else ""
        relevant = bool(tokens) and not query_genre
        sort = sort or ("relevance" if relevant else "popular")
        if sort == "relevance" and relevant:
            like = " ".join(tokens).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            order = ("CASE WHEN a.title_norm LIKE ? ESCAPE '\\' THEN 0 WHEN a.artist_norm LIKE ? ESCAPE '\\' THEN 1 ELSE 2 END, "
                     "a.popularity DESC, a.title")
            order_params: tuple = (like, like)
        else:
            order, order_params = SORTS.get(sort) or SORTS["popular"], ()
        total = self._query(f"SELECT count(*) FROM albums a {count_clause}", tuple(params))[0][0]
        rows = self._query(f"SELECT {COLUMNS} FROM albums a {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                           (*params, *order_params, limit, offset))
        return [_album(r) for r in rows], total


@lru_cache
def get_catalog() -> Catalog:
    return Catalog(catalog_path())
