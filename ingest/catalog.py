"""Build the site catalog and the model-to-catalog ID map (M7 catalog, M5 mapping).

    python -m ingest.catalog --model-dir data/model --mb-dir data/musicbrainz --out data/catalog.db

Inputs: the model's albums.parquet (recs.preprocess), release_groups.parquet and artists.parquet
(ingest.musicbrainz) and, if present, tables from the MusicBrainz core dump in <mb-dir>/core/mbdump/:
release, release_group and artist_credit for MBID and release-title matching,
release_group_gid_redirect so ids retired by MusicBrainz merges still resolve (album_redirects), and
medium, track and medium_format for track lists (album_tracks; see tracklists()), and genre,
l_genre_genre, link and link_type for the subgenre tree (genre_parents, genre_tree; see genre_tree()), and
url, l_release_url and l_release_group_url for Spotify and Apple Music links (album_links; see streaming_links()).

Each model album is matched to at most one MusicBrainz release group, by the first rule that hits:
    1 exact         the dataset's artist and title equal the credit and title (after normalizing)
    2 mbid          the dataset MBID is a release in the group (or the group itself), and one of
                    the group's credited artists (name or alias) is the dataset artist
    3 name          artist credit + title key, built with the same DuckDB macros as the model keys
    4 release-name  the key of any release in the group ("Pure Heroine (Extended)")
    5 alias         a credited artist's name or alias + title key (single-artist credits)
    6 co-artist     any one credited artist + title key ("Her Loss" by Drake & 21 Savage)
When a key fits several release groups, the one whose exact title matches the dataset's title wins,
then the most album-like one (primary type Album, then EP, no secondary types such as Compilation or
Live), then the earliest release. Those rows get confidence 0.8.
Unmatched model albums stay in the model (they still link users) but are never shown.

The catalog is the set of matched release groups. Output is a standalone SQLite file the API opens
read-only; rebuilding it never touches user data. M6 moves these tables to PostgreSQL.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
from pathlib import Path

import duckdb

from recs.preprocess import _define_macros, _sql_str

SCHEMA_VERSION = "7"     # 2: artist popularity, artist_search, album_redirects (M7); 3: album_tracks (ADR 0013);
                         # 4: country, ratings, genre tree for browse filters (ADR 0015); 5: album_links (ADR 0016); 6-7: album_links edition hints, candidates
# Medium formats that hold video, not the album's tracks (a bonus DVD in a CD + DVD set).
VIDEO_FORMATS = ("DVD", "DVD-Video", "DVD-R Video", "MiniDVD", "MiniDVD-Video", "Minimax DVD", "Minimax DVD-Video",
                 "DualDisc (DVD-Video side)", "DVDplus (DVD-Video side)", "VinylDisc (DVD side)", "Data DVD", "Data DVD-R",
                 "Blu-ray", "Blu-ray-R", "Ultra HD Blu-ray", "HD-DVD", "VHS", "Betamax", "Betacam SP", "VHD", "CED",
                 "LaserDisc", "8\" LaserDisc", "12\" LaserDisc", "VCD", "SVCD", "UMD", "CDV")
COVER_URL = "https://coverartarchive.org/release-group/{mbid}/front-250"
METHODS = ("exact", "mbid", "name", "release-name", "alias", "co-artist")
MEDIUM_WIDTH, TRACK_WIDTH = 9, 12   # columns in the core dump's medium and track files
GENRE_WIDTH, L_GENRE_GENRE_WIDTH, LINK_WIDTH, LINK_TYPE_WIDTH = 6, 9, 11, 16
URL_WIDTH, L_URL_WIDTH = 5, 9
# Words in a release's title or disambiguation that mark it as something other than the regular album.
EDITION_WORDS = r"(?i)deluxe|expanded|anniversary|bonus|collector|limited|special edition|super|box set|demos|outtakes|\bxx\b|reissue"
# Streaming links MusicBrainz editors attach to releases and release groups: (service, URL filter,
# id pattern, canonical prefix). An Apple album id from the US store (or with no store) is linked without
# a country, so it opens in the listener's own store; one known only from another country's store keeps
# that country, since the album may not exist elsewhere (half of a sample of country-less links 404'd).
STREAMING = (
    ("spotify", "open.spotify.com/album/", r"open\.spotify\.com/album/([A-Za-z0-9]+)", "https://open.spotify.com/album/"),
    ("apple_music", "apple.com/", r"apple\.com/(?:[a-z]{2}/)?album/(?:[^/?#]+/)?(?:id)?([0-9]+)", "https://music.apple.com/album/"),
)
# Genre relationships that put one genre inside another's family for browsing. "subgenre" links
# parent -> child; "fusion of" links the fusion -> each genre it fuses ("ambient dub" -> ambient, dub).
FAMILY_LINKS = ("subgenre", "fusion of")
GENRE_DEPTH = 6          # longest parent chain followed (guards against cycles)
LINK_CANDIDATES = 5      # streaming links kept per album and service
RATING_PRIOR_VOTES = 10  # Bayesian average: ratings with few votes lean toward the catalog mean (ADR 0015)
TITLE_KEY = "CASE WHEN norm(strip_edition({t})) <> '' THEN norm(strip_edition({t})) ELSE norm({t}) END"

SCHEMA = """
CREATE TABLE albums (
    id TEXT PRIMARY KEY,              -- release-group MBID
    mbid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    artist TEXT NOT NULL,             -- artist credit as displayed
    title_norm TEXT NOT NULL,
    artist_norm TEXT NOT NULL,
    primary_artist_id TEXT,
    release_date TEXT,
    year INTEGER,
    primary_type TEXT,
    secondary_types TEXT NOT NULL,    -- JSON list
    genres TEXT NOT NULL,             -- JSON list, release group's own genres, else its first artist's
    cover_url TEXT,
    popularity INTEGER NOT NULL,      -- listeners in the model, summed over mapped model albums
    metadata_updated_at TEXT NOT NULL,
    country TEXT,                     -- ISO 3166 code of the first credited artist's country
    rating REAL,                      -- MusicBrainz community rating, 0-5; NULL without votes
    rating_votes INTEGER NOT NULL,
    rating_score REAL                 -- rating shrunk toward the catalog mean (RATING_PRIOR_VOTES); NULL without votes
);
-- One index per browse sort, matching app.catalog.SORTS exactly, so a page stops after its rows.
CREATE INDEX albums_popularity ON albums (popularity DESC, title_norm);
CREATE INDEX albums_newest ON albums (release_date DESC, popularity DESC);
CREATE INDEX albums_oldest ON albums (release_date IS NULL, release_date, popularity DESC);
CREATE INDEX albums_rated ON albums (rating_score DESC, rating_votes DESC, popularity DESC);
CREATE INDEX albums_title ON albums (title_norm, popularity DESC);
CREATE INDEX albums_year ON albums (year);
CREATE INDEX albums_country ON albums (country, popularity DESC);
CREATE TABLE artists (id TEXT PRIMARY KEY, mbid TEXT NOT NULL UNIQUE, name TEXT NOT NULL, sort_name TEXT,
                      popularity INTEGER NOT NULL);   -- listeners summed over the catalog albums crediting them
CREATE INDEX artists_popularity ON artists (popularity DESC);
CREATE VIRTUAL TABLE artist_search USING fts5(artist_id UNINDEXED, name, aliases, tokenize = "unicode61 remove_diacritics 2");
CREATE TABLE album_redirects (old_id TEXT PRIMARY KEY, album_id TEXT NOT NULL);   -- merged-away release-group MBIDs
CREATE TABLE album_artists (album_id TEXT NOT NULL, artist_id TEXT NOT NULL, position INTEGER NOT NULL,
                            PRIMARY KEY (album_id, position));
CREATE INDEX album_artists_artist ON album_artists (artist_id);
CREATE TABLE album_genres (album_id TEXT NOT NULL, genre TEXT NOT NULL, PRIMARY KEY (genre, album_id));
CREATE INDEX album_genres_album ON album_genres (album_id);
-- albums/listeners: tagged with the genre itself; albums_all/listeners_all: with it or any subgenre.
CREATE TABLE genres (name TEXT PRIMARY KEY, albums INTEGER NOT NULL, listeners INTEGER NOT NULL,
                     albums_all INTEGER NOT NULL, listeners_all INTEGER NOT NULL);
CREATE TABLE genre_parents (genre TEXT NOT NULL, parent TEXT NOT NULL, PRIMARY KEY (genre, parent));
CREATE INDEX genre_parents_parent ON genre_parents (parent);
-- Every genre with each of its ancestors, and itself: filtering by `ancestor` includes subgenres.
CREATE TABLE genre_tree (ancestor TEXT NOT NULL, genre TEXT NOT NULL, PRIMARY KEY (ancestor, genre));
-- Every album under each genre family it belongs to, by albums.rowid: the browse genre filter is one
-- key lookup per album. Filled after the final VACUUM, which may renumber rowids; never VACUUM after.
CREATE TABLE album_family (ancestor TEXT NOT NULL, album_rowid INTEGER NOT NULL, PRIMARY KEY (ancestor, album_rowid)) WITHOUT ROWID;
CREATE TABLE model_albums (model_idx INTEGER PRIMARY KEY, album_key TEXT NOT NULL, mbid TEXT,
                           title TEXT NOT NULL, artist TEXT NOT NULL, n_users INTEGER NOT NULL);
CREATE TABLE album_id_map (model_idx INTEGER PRIMARY KEY, album_id TEXT, match_method TEXT, confidence REAL);
CREATE INDEX album_id_map_album ON album_id_map (album_id);
CREATE VIRTUAL TABLE album_search USING fts5(    -- also_known_as: the dataset's spellings ("Emotion" for "E•MO•TION")
    album_id UNINDEXED, title, artist, genres, also_known_as, tokenize = "unicode61 remove_diacritics 2");
-- One release's track list per album. media: JSON [{"position", "format", "title",
-- "tracks": [[number, title, artist credit or null when it is the album's, length in ms or null], ...]}]
CREATE TABLE album_tracks (album_id TEXT PRIMARY KEY, release_id TEXT NOT NULL, media TEXT NOT NULL);
-- One Spotify and one Apple Music album link per album, where MusicBrainz has one (ADR 0016).
-- Up to LINK_CANDIDATES links per album and service, best first (rank 1). edition is MusicBrainz's hint:
-- 0 the regular album, 1 a remaster of it, 2 a deluxe, expanded or other edition. The API checks each
-- service's own title before using one (app/listen.py), since the hint is often wrong.
CREATE TABLE album_links (album_id TEXT NOT NULL, service TEXT NOT NULL, rank INTEGER NOT NULL, url TEXT NOT NULL,
                          edition INTEGER NOT NULL, PRIMARY KEY (album_id, service, rank)) WITHOUT ROWID;
CREATE TABLE catalog_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _core_csv(path: Path, width: int) -> str:
    """A DuckDB read_csv() over a PostgreSQL COPY text file (tab separated, \\N for null) with `width` columns."""
    return f"""read_csv({_sql_str(str(path))}, delim = '\t', header = false, quote = '', escape = '', nullstr = '\\N',
                        all_varchar = true, null_padding = true, ignore_errors = true,
                        columns = {{{", ".join(f"'column{i:02d}': 'VARCHAR'" for i in range(width))}}})"""


def _core_table(con: duckdb.DuckDBPyConnection, path: Path, columns: dict[str, int], width: int, name: str) -> bool:
    """Load selected columns of a core dump table into DuckDB table `name`; False when the file is missing."""
    if not path.exists():
        return False
    cols = ", ".join(f"column{i:02d} AS {c}" for c, i in columns.items())
    con.execute(f"CREATE TABLE {name} AS SELECT {cols} FROM {_core_csv(path, width)}")
    return True


def match(model_dir: str, mb_dir: str, con: duckdb.DuckDBPyConnection | None = None, log=print) -> tuple[duckdb.DuckDBPyConnection, dict]:
    """Returns a DuckDB connection holding tables `matches` (model_idx, rg_mbid, method, confidence),
    `model` and `rg`, plus a report dict."""
    con = con or duckdb.connect()
    _define_macros(con)
    mb = Path(mb_dir)
    con.execute(f"CREATE TABLE model AS SELECT album_idx AS model_idx, album_key, artist, title, mbid, n_users FROM {_sql_str(str(Path(model_dir) / 'albums.parquet'))}")
    con.execute(f"CREATE TABLE rg AS SELECT * FROM {_sql_str(str(mb / 'release_groups.parquet'))}")
    con.execute(f"CREATE TABLE ar AS SELECT * FROM {_sql_str(str(mb / 'artists.parquet'))}")
    # Rank release groups so ties pick the most album-like one.
    con.execute("""CREATE TABLE rg_rank AS SELECT rg_mbid,
        (CASE primary_type WHEN 'Album' THEN 0 WHEN 'EP' THEN 1 WHEN 'Single' THEN 3 ELSE 2 END) * 2
          + (CASE WHEN len(secondary_types) = 0 THEN 0 ELSE 1 END) AS type_rank,
        coalesce(nullif(first_release_date, ''), '9999') AS date_rank FROM rg""")

    con.execute(f"CREATE TABLE rg_title AS SELECT rg_mbid, {TITLE_KEY.format(t='title')} AS t, norm(title) AS exact FROM rg")
    con.execute("CREATE TABLE model_titles AS SELECT DISTINCT split_part(album_key, ' | ', 2) AS t FROM model")
    core = mb / "core" / "mbdump"
    has_core = (_core_table(con, core / "release", {"id": 0, "gid": 1, "name": 2, "artist_credit": 3, "release_group": 4, "status": 5,
                                                     "comment": 10}, 14, "rel")
                and _core_table(con, core / "release_group", {"id": 0, "gid": 1}, 8, "relg")
                and _core_table(con, core / "artist_credit", {"id": 0, "name": 1}, 7, "ac"))
    if has_core and _core_table(con, core / "release_group_gid_redirect", {"gid": 0, "new_id": 1}, 3, "rgr"):
        con.execute("CREATE TABLE redirects AS SELECT rgr.gid AS old_id, relg.gid AS album_id FROM rgr JOIN relg ON relg.id = rgr.new_id")
    if has_core:
        con.execute("CREATE TABLE release AS SELECT rel.gid AS release_mbid, rel.name, ac.name AS credit, relg.gid AS rg_mbid FROM rel JOIN relg ON relg.id = rel.release_group JOIN ac ON ac.id = rel.artist_credit")
        mbid_sql = """SELECT m.model_idx, r.rg_mbid FROM model m JOIN release r ON r.release_mbid = m.mbid
                      UNION SELECT m.model_idx, g.rg_mbid FROM model m JOIN rg g ON g.rg_mbid = m.mbid"""
    else:
        log("core dump tables not found: matching by names only")
        mbid_sql = "SELECT m.model_idx, g.rg_mbid FROM model m JOIN rg g ON g.rg_mbid = m.mbid"
    con.execute(f"CREATE TABLE mbid_raw AS {mbid_sql}")

    # Every name a release group answers to: its credit, and each credited artist's name and aliases
    # ('alias' for single-artist credits, 'co-artist' when several artists share the credit). Only for
    # release groups that could match (a model title key, or an MBID target): all of them would not
    # fit in memory, since prolific credits have hundreds of aliases and thousands of release groups.
    con.execute("""CREATE TABLE rg_live AS
        SELECT rg_mbid FROM rg_title SEMI JOIN model_titles USING (t) UNION SELECT rg_mbid FROM mbid_raw""")
    con.execute("""CREATE TABLE rg_names AS
        SELECT rg_mbid, norm(artist_credit) AS n, 'name' AS kind FROM rg SEMI JOIN rg_live USING (rg_mbid)
        UNION
        SELECT x.rg_mbid, norm(u.n), x.kind FROM (
            SELECT rg_mbid, unnest(artist_mbids) AS artist_mbid,
                   CASE WHEN len(artist_mbids) = 1 THEN 'alias' ELSE 'co-artist' END AS kind
            FROM rg SEMI JOIN rg_live USING (rg_mbid)) x
        JOIN ar USING (artist_mbid), unnest(list_concat([ar.name], ar.aliases)) u(n)""")
    keys = ["SELECT n.n || ' | ' || t.t AS k, rg_mbid, n.kind AS method FROM rg_names n JOIN rg_title t USING (rg_mbid)"]
    if has_core:
        keys.append(f"""SELECT DISTINCT norm(credit) || ' | ' || t, rg_mbid, 'release-name' FROM (
                          SELECT credit, rg_mbid, {TITLE_KEY.format(t='name')} AS t FROM release) SEMI JOIN model_titles USING (t)""")
    con.execute("CREATE TABLE keys AS " + " UNION ALL ".join(keys))
    # Dataset MBIDs are sometimes wrong (a cover album or another artist's record with the same title),
    # so an MBID match must agree on the artist: that drops Dream Theater's "Dark Side of the Moon" for
    # Pink Floyd. Titles may differ ("Emotion" -> "E•MO•TION"); same-artist mix-ups are left to the
    # `exact` rule, which outranks MBIDs.
    con.execute("""CREATE TABLE candidates AS
        SELECT c.model_idx, c.rg_mbid, 'mbid' AS method FROM mbid_raw c JOIN model m USING (model_idx)
        WHERE EXISTS (SELECT 1 FROM rg_names n WHERE n.rg_mbid = c.rg_mbid AND n.n = split_part(m.album_key, ' | ', 1))
        UNION ALL
        SELECT m.model_idx, k.rg_mbid,
               CASE WHEN k.method = 'name' AND t.exact = norm(m.title) THEN 'exact' ELSE k.method END
        FROM model m JOIN keys k ON k.k = m.album_key JOIN rg_title t USING (rg_mbid)""")
    con.execute(f"""CREATE TABLE matches AS
        WITH best_method AS (
            SELECT model_idx, min(list_position({list(METHODS)}, method)) AS pos FROM candidates GROUP BY 1),
        pool AS (
            SELECT DISTINCT c.model_idx, c.rg_mbid, c.method FROM candidates c JOIN best_method b
            ON b.model_idx = c.model_idx AND list_position({list(METHODS)}, c.method) = b.pos)
        SELECT model_idx, arg_min(rg_mbid, (exact_rank, type_rank, date_rank, rg_mbid)) AS rg_mbid, any_value(method) AS method,
               CAST(CASE WHEN count(*) > 1 THEN 0.8 ELSE 1.0 END AS DOUBLE) AS confidence
        FROM (SELECT pool.*, rg_rank.type_rank, rg_rank.date_rank,
                     CASE WHEN norm(g.title) = norm(m.title) THEN 0 ELSE 1 END AS exact_rank
              FROM pool JOIN rg_rank USING (rg_mbid) JOIN rg g USING (rg_mbid) JOIN model m USING (model_idx))
        GROUP BY model_idx""")

    total_users = con.execute("SELECT sum(n_users) FROM model").fetchone()[0]
    report = {"core_dump": has_core, "model_albums": con.execute("SELECT count(*) FROM model").fetchone()[0],
              "by_method": {}, "catalog_albums": con.execute("SELECT count(DISTINCT rg_mbid) FROM matches").fetchone()[0]}
    for method, n, users in con.execute("SELECT method, count(*), sum(n_users) FROM matches JOIN model USING (model_idx) GROUP BY 1").fetchall():
        report["by_method"][method] = {"albums": n, "listening_share": round(users / total_users, 4)}
    matched, users = con.execute("SELECT count(*), sum(n_users) FROM matches JOIN model USING (model_idx)").fetchone()
    report["matched_albums"], report["listening_covered"] = matched, round((users or 0) / total_users, 4)
    report["ambiguous"] = con.execute("SELECT count(*) FROM matches WHERE confidence < 1").fetchone()[0]
    for threshold in (1000, 100, 10):
        n, hit = con.execute(f"SELECT count(*), count(rg_mbid) FROM model LEFT JOIN matches USING (model_idx) WHERE n_users >= {threshold}").fetchone()
        report[f"matched_share_{threshold}_plus_listeners"] = round(hit / n, 4) if n else None
    report["top_unmatched"] = [{"artist": a, "title": t, "listeners": n} for a, t, n in con.execute(
        "SELECT artist, title, n_users FROM model LEFT JOIN matches USING (model_idx) WHERE rg_mbid IS NULL ORDER BY n_users DESC LIMIT 30").fetchall()]
    return con, report


def tracklists(con: duckdb.DuckDBPyConnection, mb_dir: str, log=print) -> int:
    """DuckDB table `tracklist` (rg_mbid, release_mbid, media JSON): one release's tracks per matched
    release group. Returns the number of albums with a track list (0 without the core tables).

    The release: among the group's official releases (any release if none is official), the most
    common audio track count wins (so a deluxe or bonus-track edition loses to the standard one), ties
    going to the shorter list; then a CD or digital release (plain track numbers, not vinyl or
    cassette sides), then the release MusicBrainz has had longest (lowest id). Video media
    and data tracks are left out. A track's artist is kept only when it differs from the release's."""
    core = Path(mb_dir) / "core" / "mbdump"
    if not all((core / t).exists() for t in ("release", "release_group", "artist_credit", "medium", "track", "medium_format")):
        log("medium/track tables not found: no track lists")
        return 0
    _core_table(con, core / "medium", {"id": 0, "release": 1, "position": 2, "format": 3, "name": 4, "track_count": 7}, MEDIUM_WIDTH, "med")
    _core_table(con, core / "medium_format", {"id": 0, "name": 1}, 8, "fmt")
    video = ", ".join(_sql_str(f) for f in VIDEO_FORMATS)
    con.execute("""CREATE TABLE cand_rel AS
        SELECT CAST(rel.id AS BIGINT) AS rel_id, rel.gid AS release_mbid, rel.status = '1' AS official, rel.artist_credit, relg.gid AS rg_mbid
        FROM rel JOIN relg ON relg.id = rel.release_group WHERE relg.gid IN (SELECT rg_mbid FROM matches)""")
    con.execute(f"""CREATE TABLE audio_media AS
        SELECT CAST(m.id AS BIGINT) AS medium_id, c.rel_id, CAST(m.position AS INTEGER) AS position, f.name AS format,
               nullif(m.name, '') AS title, CAST(m.track_count AS INTEGER) AS track_count
        FROM med m JOIN cand_rel c ON c.rel_id = CAST(m.release AS BIGINT) LEFT JOIN fmt f ON f.id = m.format
        WHERE f.name IS NULL OR f.name NOT IN ({video})""")
    con.execute("""CREATE TABLE chosen AS
        WITH sized AS (SELECT c.*, s.tracks, s.format_rank FROM cand_rel c JOIN (
                           SELECT rel_id, sum(track_count) AS tracks,
                                  max(CASE WHEN format IN ('CD', 'Digital Media') THEN 0 ELSE 1 END) AS format_rank
                           FROM audio_media GROUP BY 1 HAVING sum(track_count) > 0) s USING (rel_id)),
             pool AS (SELECT * FROM sized s WHERE official OR NOT EXISTS (SELECT 1 FROM sized o WHERE o.rg_mbid = s.rg_mbid AND o.official)),
             best AS (SELECT rg_mbid, arg_max(tracks, (n, -tracks)) AS tracks FROM (
                           SELECT rg_mbid, tracks, count(*) AS n FROM pool GROUP BY 1, 2) GROUP BY 1)
        SELECT rg_mbid, arg_min(rel_id, (format_rank, rel_id)) AS rel_id FROM pool JOIN best USING (rg_mbid, tracks) GROUP BY 1""")
    con.execute("""CREATE TABLE chosen_media AS
        SELECT a.*, row_number() OVER (PARTITION BY a.rel_id ORDER BY a.position) AS disc
        FROM audio_media a SEMI JOIN chosen USING (rel_id)""")
    con.execute(f"""CREATE TABLE trk AS
        SELECT CAST(column03 AS BIGINT) AS medium_id, CAST(column04 AS INTEGER) AS position, column05 AS number,
               column06 AS title, column07 AS artist_credit, TRY_CAST(column08 AS BIGINT) AS length
        FROM {_core_csv(core / "track", TRACK_WIDTH)}
        WHERE coalesce(column11, 'f') <> 't' AND CAST(column03 AS BIGINT) IN (SELECT medium_id FROM chosen_media)""")
    con.execute("""CREATE TABLE tracklist AS
        WITH discs AS (
            SELECT m.rel_id, m.disc, any_value(m.format) AS format, any_value(m.title) AS title,
                   to_json(list(json_array(t.number, t.title, CASE WHEN t.artist_credit <> c.artist_credit THEN ac.name END, t.length)
                                ORDER BY t.position)) AS tracks
            FROM trk t JOIN chosen_media m USING (medium_id) JOIN cand_rel c USING (rel_id) LEFT JOIN ac ON ac.id = t.artist_credit
            GROUP BY m.rel_id, m.disc)
        SELECT ch.rg_mbid, c.release_mbid,
               to_json(list(json_object('position', d.disc, 'format', d.format, 'title', d.title, 'tracks', d.tracks) ORDER BY d.disc))::VARCHAR AS media
        FROM chosen ch JOIN cand_rel c USING (rel_id) JOIN discs d USING (rel_id) GROUP BY ch.rg_mbid, c.release_mbid""")
    return con.execute("SELECT count(*) FROM tracklist").fetchone()[0]


def genre_tree(con: duckdb.DuckDBPyConnection, mb_dir: str, log=print) -> int:
    """DuckDB tables genre_edge (genre, parent) from MusicBrainz's genre relationships and
    genre_closure (ancestor, genre), every genre with its ancestors and itself. Without the core
    genre tables both are empty and genres stand alone. Returns the number of edges."""
    core = Path(mb_dir) / "core" / "mbdump"
    con.execute("CREATE TABLE genre_edge (genre VARCHAR, parent VARCHAR)")
    con.execute("CREATE TABLE genre_closure (ancestor VARCHAR, genre VARCHAR)")
    loaded = (_core_table(con, core / "genre", {"id": 0, "name": 2}, GENRE_WIDTH, "mb_genre")
              and _core_table(con, core / "l_genre_genre", {"link": 1, "e0": 2, "e1": 3}, L_GENRE_GENRE_WIDTH, "lgg")
              and _core_table(con, core / "link", {"id": 0, "link_type": 1}, LINK_WIDTH, "lnk")
              and _core_table(con, core / "link_type", {"id": 0, "t0": 4, "t1": 5, "name": 6}, LINK_TYPE_WIDTH, "lt"))
    if not loaded:
        log("  no genre tables in the core dump: subgenres are off")
        return 0
    names = ", ".join(_sql_str(n) for n in FAMILY_LINKS)
    con.execute(f"""INSERT INTO genre_edge SELECT DISTINCT
            CASE WHEN lt.name = 'subgenre' THEN g1.name ELSE g0.name END,
            CASE WHEN lt.name = 'subgenre' THEN g0.name ELSE g1.name END
        FROM lgg JOIN lnk ON lnk.id = lgg.link JOIN lt ON lt.id = lnk.link_type
        JOIN mb_genre g0 ON g0.id = lgg.e0 JOIN mb_genre g1 ON g1.id = lgg.e1
        WHERE lt.t0 = 'genre' AND lt.t1 = 'genre' AND lt.name IN ({names})""")
    con.execute(f"""INSERT INTO genre_closure WITH RECURSIVE up(ancestor, genre, depth) AS (
            SELECT name, name, 0 FROM mb_genre
            UNION SELECT e.parent, up.genre, up.depth + 1 FROM up JOIN genre_edge e ON e.genre = up.ancestor
                  WHERE up.depth < {GENRE_DEPTH})
        SELECT DISTINCT ancestor, genre FROM up""")
    edges = con.execute("SELECT count(*) FROM genre_edge").fetchone()[0]
    log(f"  genre tree: {edges:,} parent links")
    return edges


def streaming_links(con: duckdb.DuckDBPyConnection, mb_dir: str, log=print) -> dict:
    """DuckDB table album_link (rg_mbid, service, url, edition): one link per album and service, from the
    URL relationships of the group's releases and of the group itself. MusicBrainz files reissues in the
    same group ("Illmatic XX", "OK Computer OKNOTOK 1997 2017"), so each candidate is first ranked by how
    regular its release is (owner request: always the regular album), as the worst of:
      - its title: the album's own (0), the album's plus a remaster tag (1), anything else (2);
      - its disambiguation: edition words (2), a remaster (1);
      - its track count: more tracks than the standard edition's (2) (the track list's release, ADR 0013).
    A link on the group itself counts as regular. Ties go to the track list's release, the group's link,
    the oldest official release, then the oldest release. Without the core URL tables it stays empty."""
    core = Path(mb_dir) / "core" / "mbdump"
    con.execute("CREATE TABLE album_link (rg_mbid VARCHAR, service VARCHAR, rank INTEGER, url VARCHAR, edition INTEGER)")
    has_rel = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'rel'").fetchone()[0]
    if not (has_rel and all((core / t).exists() for t in ("url", "l_release_url", "l_release_group_url"))):
        log("  no URL tables in the core dump: no streaming links")
        return {}
    like = " OR ".join(f"column02 LIKE {_sql_str('%' + f + '%')}" for _, f, _, _ in STREAMING)
    con.execute(f"CREATE TABLE stream_url AS SELECT column00 AS id, column02 AS url FROM {_core_csv(core / 'url', URL_WIDTH)} WHERE {like}")
    con.execute(f"""CREATE TABLE stream_rel AS SELECT column02 AS rel_id, column03 AS url_id FROM {_core_csv(core / 'l_release_url', L_URL_WIDTH)}
                    WHERE column03 IN (SELECT id FROM stream_url)""")
    con.execute(f"""CREATE TABLE stream_rg AS SELECT column02 AS rg_id, column03 AS url_id FROM {_core_csv(core / 'l_release_group_url', L_URL_WIDTH)}
                    WHERE column03 IN (SELECT id FROM stream_url)""")
    has = lambda t: con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [t]).fetchone()[0]
    chosen = ("SELECT rg_mbid, rel_id FROM chosen" if has("chosen")
              else "SELECT NULL::VARCHAR AS rg_mbid, NULL::BIGINT AS rel_id WHERE false")
    # Audio tracks only, as for track lists: a bonus DVD doesn't make a release an expanded edition.
    tracks = ("SELECT rel_id, sum(track_count) AS tracks FROM audio_media GROUP BY 1" if has("audio_media")
              else "SELECT NULL::BIGINT AS rel_id, NULL::BIGINT AS tracks WHERE false")
    edition_re = _sql_str(EDITION_WORDS)
    services = " UNION ALL ".join(f"SELECT {_sql_str(name)} AS service, {_sql_str(pattern)} AS pattern, {_sql_str(prefix)} AS prefix"
                                  for name, _, pattern, prefix in STREAMING)
    con.execute(f"""CREATE TABLE album_link_all AS
        WITH rel_tracks AS ({tracks}),
        standard AS (SELECT ch.rg_mbid, t.tracks FROM ({chosen}) ch JOIN rel_tracks t USING (rel_id)),
        linked AS (
            SELECT g.gid AS rg_mbid, u.url, CASE WHEN ch.rel_id IS NOT NULL THEN 0 WHEN r.status = '1' THEN 2 ELSE 3 END AS pref,
                   TRY_CAST(r.id AS BIGINT) AS rel_order,
                   greatest(
                       CASE WHEN norm(r.name) = norm(t.title) THEN 0
                            WHEN norm(strip_edition(r.name)) = norm(strip_edition(t.title))
                                 AND regexp_matches(r.name, '(?i)remaster') AND NOT regexp_matches(r.name, {edition_re}) THEN 1
                            ELSE 2 END,
                       CASE WHEN regexp_matches(coalesce(r.comment, ''), {edition_re}) THEN 2
                            WHEN regexp_matches(coalesce(r.comment, ''), '(?i)remaster') THEN 1 ELSE 0 END,
                       CASE WHEN rt.tracks > st.tracks THEN 2 ELSE 0 END) AS edition
            FROM stream_rel l JOIN stream_url u ON u.id = l.url_id JOIN rel r ON r.id = l.rel_id JOIN relg g ON g.id = r.release_group
            JOIN rg t ON t.rg_mbid = g.gid
            LEFT JOIN ({chosen}) ch ON ch.rg_mbid = g.gid AND ch.rel_id = TRY_CAST(r.id AS BIGINT)
            LEFT JOIN rel_tracks rt ON rt.rel_id = TRY_CAST(r.id AS BIGINT)
            LEFT JOIN standard st ON st.rg_mbid = g.gid
            UNION ALL
            SELECT g.gid, u.url, 1, 0, 0 FROM stream_rg l JOIN stream_url u ON u.id = l.url_id JOIN relg g ON g.id = l.rg_id)
        , parsed AS (
            SELECT linked.*, s.service, s.prefix, regexp_extract(linked.url, s.pattern, 1) AS item,
                   CASE WHEN s.service = 'apple_music' THEN regexp_extract(linked.url, 'apple\\.com/([a-z]{{2}})/', 1) ELSE '' END AS store
            FROM linked, ({services}) s)
        SELECT rg_mbid, service, pref, rel_order, edition, store IN ('', 'us') AS anywhere,
               CASE WHEN store IN ('', 'us') THEN prefix || item ELSE 'https://music.apple.com/' || store || '/album/' || item END AS url
        FROM parsed WHERE item <> ''""")
    con.execute(f"""INSERT INTO album_link
        SELECT rg_mbid, service, rank, url, edition FROM (
            SELECT *, row_number() OVER (PARTITION BY rg_mbid, service ORDER BY edition, NOT anywhere, pref, rel_order, url) AS rank
            FROM (SELECT rg_mbid, service, url, min(edition) AS edition, bool_or(anywhere) AS anywhere, min(pref) AS pref,
                         min(rel_order) AS rel_order
                  FROM album_link_all WHERE rg_mbid IN (SELECT rg_mbid FROM matches) GROUP BY 1, 2, 3))
        WHERE rank <= {LINK_CANDIDATES}""")
    counts = {f"{s} albums": n for s, n in con.execute("SELECT service, count(DISTINCT rg_mbid) FROM album_link GROUP BY 1 ORDER BY 1").fetchall()}
    log(f"  streaming links: {counts}")
    return counts


def write_catalog(con: duckdb.DuckDBPyConnection, out_path: str, report: dict, source: dict) -> None:
    """Write matched release groups and the ID map into a fresh SQLite file."""
    con.execute("""CREATE TABLE cat AS
        SELECT g.rg_mbid AS id, g.title, g.artist_credit AS artist, norm(g.title) AS title_norm, norm(g.artist_credit) AS artist_norm,
               g.artist_mbids[1] AS primary_artist_id, nullif(g.first_release_date, '') AS release_date,
               TRY_CAST(substr(g.first_release_date, 1, 4) AS INTEGER) AS year, g.primary_type,
               to_json(g.secondary_types)::VARCHAR AS secondary_types,
               to_json(CASE WHEN len(g.genres) > 0 THEN g.genres ELSE coalesce(list_slice(a.genres, 1, 3), []) END)::VARCHAR AS genres,
               p.popularity, a.country, g.rating, coalesce(g.rating_votes, 0) AS rating_votes
        FROM rg g JOIN (SELECT rg_mbid, CAST(sum(n_users) AS BIGINT) AS popularity FROM matches JOIN model USING (model_idx) GROUP BY 1) p USING (rg_mbid)
        LEFT JOIN ar a ON a.artist_mbid = g.artist_mbids[1]""")
    out = Path(out_path)
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(SCHEMA)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    mean = con.execute("SELECT avg(rating) FROM cat WHERE rating_votes > 0").fetchone()[0] or 0.0
    albums = con.execute(f"""SELECT id, title, artist, title_norm, artist_norm, primary_artist_id, release_date, year, primary_type,
                                    secondary_types, genres, popularity, country,
                                    CASE WHEN rating_votes > 0 THEN rating END, rating_votes,
                                    CASE WHEN rating_votes > 0 THEN (rating_votes * rating + {RATING_PRIOR_VOTES} * {mean})
                                                                    / (rating_votes + {RATING_PRIOR_VOTES}) END
                             FROM cat""").fetchall()
    db.executemany("INSERT INTO albums VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                   [(r[0], r[0], *r[1:10], r[10], COVER_URL.format(mbid=r[0]), r[11], now, *r[12:16]) for r in albums])
    aka = dict(con.execute("""SELECT x.rg_mbid, string_agg(DISTINCT m.artist || ' ' || m.title, ' / ')
                              FROM matches x JOIN model m USING (model_idx) GROUP BY 1""").fetchall())
    db.executemany("INSERT INTO album_search VALUES (?, ?, ?, ?, ?)",
                   [(r[0], r[1], r[2], " ".join(json.loads(r[10])), aka.get(r[0], "")) for r in albums])
    db.executemany("INSERT INTO album_artists VALUES (?, ?, ?)", con.execute(
        "SELECT g.rg_mbid, a.mbid, a.pos FROM rg g JOIN cat ON cat.id = g.rg_mbid, unnest(g.artist_mbids) WITH ORDINALITY a(mbid, pos)").fetchall())
    artists = con.execute("""
        SELECT a.artist_mbid, a.name, a.sort_name, CAST(sum(cat.popularity) AS BIGINT), array_to_string(a.aliases, ' / ')
        FROM ar a JOIN (SELECT DISTINCT g.rg_mbid, unnest(g.artist_mbids) AS m FROM rg g JOIN cat ON cat.id = g.rg_mbid) u ON u.m = a.artist_mbid
        JOIN cat ON cat.id = u.rg_mbid GROUP BY ALL""").fetchall()
    db.executemany("INSERT INTO artists VALUES (?, ?, ?, ?, ?)", [(r[0], r[0], r[1], r[2], r[3]) for r in artists])
    db.executemany("INSERT INTO artist_search VALUES (?, ?, ?)", [(r[0], r[1], r[4] or "") for r in artists])
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'redirects'").fetchone()[0]:
        db.executemany("INSERT INTO album_redirects VALUES (?, ?)", con.execute(
            "SELECT DISTINCT r.old_id, r.album_id FROM redirects r JOIN cat ON cat.id = r.album_id").fetchall())
    if con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name = 'tracklist'").fetchone()[0]:
        db.executemany("INSERT INTO album_tracks VALUES (?, ?, ?)", con.execute("SELECT rg_mbid, release_mbid, media FROM tracklist").fetchall())
    db.executemany("INSERT INTO album_genres VALUES (?, ?)",
                   [(r[0], g) for r in albums for g in dict.fromkeys(json.loads(r[10]))])
    db.executemany("INSERT INTO album_links VALUES (?, ?, ?, ?, ?)", con.execute(
        "SELECT l.rg_mbid, l.service, l.rank, l.url, l.edition FROM album_link l JOIN cat ON cat.id = l.rg_mbid").fetchall())
    db.executemany("INSERT INTO genre_parents VALUES (?, ?)", con.execute("SELECT genre, parent FROM genre_edge").fetchall())
    db.executemany("INSERT OR IGNORE INTO genre_tree VALUES (?, ?)", con.execute("SELECT ancestor, genre FROM genre_closure").fetchall())
    db.execute("INSERT OR IGNORE INTO genre_tree SELECT DISTINCT genre, genre FROM album_genres")   # genres with no MusicBrainz entry
    db.executescript("""
        CREATE TEMP TABLE direct AS SELECT genre, count(*) AS albums, sum(a.popularity) AS listeners
            FROM album_genres JOIN albums a ON a.id = album_id GROUP BY genre;
        CREATE TEMP TABLE family AS SELECT t.ancestor, count(DISTINCT ag.album_id) AS albums
            FROM genre_tree t JOIN album_genres ag ON ag.genre = t.genre GROUP BY t.ancestor;
        CREATE TEMP TABLE family_listeners AS SELECT ancestor, sum(a.popularity) AS listeners FROM
            (SELECT DISTINCT t.ancestor, ag.album_id FROM genre_tree t JOIN album_genres ag ON ag.genre = t.genre) f
            JOIN albums a ON a.id = f.album_id GROUP BY ancestor;
        INSERT INTO genres SELECT f.ancestor, coalesce(d.albums, 0), coalesce(d.listeners, 0), f.albums, l.listeners
            FROM family f JOIN family_listeners l USING (ancestor) LEFT JOIN direct d ON d.genre = f.ancestor;
    """)
    db.executemany("INSERT INTO model_albums VALUES (?, ?, ?, ?, ?, ?)",
                   con.execute("SELECT model_idx, album_key, mbid, title, artist, n_users FROM model").fetchall())
    db.executemany("INSERT INTO album_id_map VALUES (?, ?, ?, ?)", con.execute(
        "SELECT m.model_idx, x.rg_mbid, x.method, x.confidence FROM model m LEFT JOIN matches x USING (model_idx)").fetchall())
    db.executemany("INSERT INTO catalog_meta VALUES (?, ?)", [("built_at", now), ("report", json.dumps(report)),
                                                             ("source", json.dumps(source)),
                                                             ("schema_version", SCHEMA_VERSION)])
    db.commit()
    db.execute("VACUUM")
    db.execute("""INSERT INTO album_family SELECT DISTINCT t.ancestor, a.rowid
                  FROM genre_tree t JOIN album_genres ag ON ag.genre = t.genre JOIN albums a ON a.id = ag.album_id""")
    db.commit()
    db.close()
    tmp.replace(out)


def build(model_dir: str, mb_dir: str, out_path: str, log=print) -> dict:
    started = time.time()
    con, report = match(model_dir, mb_dir, log=log)
    report["albums_with_tracks"] = tracklists(con, mb_dir, log=log)
    report["genre_links"] = genre_tree(con, mb_dir, log=log)
    report["streaming_links"] = streaming_links(con, mb_dir, log=log)
    meta_path = Path(mb_dir) / "ingest_meta.json"
    source = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    write_catalog(con, out_path, report, source)
    report["seconds"] = round(time.time() - started)
    return report


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model-dir", default="data/model")
    p.add_argument("--mb-dir", default="data/musicbrainz")
    p.add_argument("--out", default="data/catalog.db")
    a = p.parse_args()
    report = build(a.model_dir, a.mb_dir, a.out)
    print(json.dumps({k: v for k, v in report.items() if k != "top_unmatched"}, indent=2))
    print("top unmatched:", *[f"  {u['artist']} - {u['title']} ({u['listeners']:,})" for u in report["top_unmatched"][:15]], sep="\n")


if __name__ == "__main__":
    main()
