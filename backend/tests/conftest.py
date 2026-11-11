"""A small world for API tests: a model and a MusicBrainz extract, built into catalog.db by the
real ingest.catalog.build, so the tests also exercise matching (names, aliases, MBIDs, unmatched)."""
import os
import uuid

import duckdb
import numpy as np
import pandas as pd
import pytest

from ingest.catalog import build
from recs.preprocess import _define_macros

def rg_id(title: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, title))


# (artist credit, title, genres) in MusicBrainz; ids are uuid5 of the title.
RELEASE_GROUPS = [
    ("Nas", "Illmatic", ["hip hop"]), ("Madvillain", "Madvillainy", ["hip hop"]),
    ("Kendrick Lamar", "To Pimp a Butterfly", ["hip hop", "jazz rap"]), ("GZA", "Liquid Swords", ["hip hop"]),
    ("Burial", "Untrue", ["electronic"]), ("Daft Punk", "Discovery", ["electronic", "house"]),
    ("Tame Impala", "Currents", ["psychedelic pop"]), ("Frank Ocean", "Blonde", ["r&b"]),
    ("Beyoncé", "Lemonade", ["r&b", "pop"]), ("Miles Davis", "Kind of Blue", ["jazz"]),
    ("Radiohead", "OK Computer", ["rock"]), ("Radiohead", "In Rainbows", ["rock"]),
    ("Radiohead", "Kid A", ["rock", "electronic"]), ("Radiohead", "Amnesiac", ["rock"]),
    ("Portishead", "Dummy", ["trip hop"]),
    # Both normalize to "return to the 36 chambers"; the instrumental one is older, so only the
    # exact-title tie-break picks the right one.
    ("Ol' Dirty Bastard", "Return to the 36 Chambers: The Dirty Version", ["hip hop"]),
    ("Ol' Dirty Bastard", "Return to the 36 Chambers: The Dirty Version Instrumentals", ["hip hop"]),
    ("Drake & 21 Savage", "Her Loss", ["hip hop"]),
    ("Pink Floyd", "The Dark Side of the Moon", ["rock"]), ("Dream Theater", "Dark Side of the Moon", ["metal"]),
    ("Taylor Swift", "THE TORTURED POETS DEPARTMENT", ["pop"]),
]
CREDITS = {"Drake & 21 Savage": ["Drake", "21 Savage"]}   # multi-artist credits; others are one artist
OLDER = {"Return to the 36 Chambers: The Dirty Version Instrumentals": "1990-01-01",
         "Kind of Blue": "1959-08-17", "Currents": "2015-07-17", "In Rainbows": "2007-10-10"}   # others: 1994-04-19
# MusicBrainz community ratings (value, votes): few votes count for less ("rated" sort, ADR 0015).
RATINGS = {"OK Computer": (4.5, 40), "Kind of Blue": (4.6, 30), "Untrue": (5.0, 1), "Illmatic": (4.2, 12), "Her Loss": (2.0, 10)}
COUNTRIES = {"Radiohead": "GB", "Portishead": "GB", "Burial": "GB", "Nas": "US", "Daft Punk": "FR"}
# MusicBrainz genre relationships: (link type, entity0, entity1). "subgenre": parent -> child;
# "fusion of": fusion -> part; "influenced by" is ignored.
GENRE_LINKS = [("subgenre", "electronic", "house"), ("subgenre", "electronic", "trip hop"),
               ("fusion of", "jazz rap", "jazz"), ("fusion of", "jazz rap", "hip hop"),
               ("subgenre", "pop", "psychedelic pop"), ("influenced by", "rock", "jazz")]
SECONDARY = {"Lemonade": ["Soundtrack"]}   # a non-studio album: listed under "other" on artist pages
ARTIST_ALIASES = {"GZA": ["GZA/Genius"]}
# Model albums as the dataset names them. "GZA/Genius" reaches Liquid Swords through the alias;
# "Bootleg Tape" has no MusicBrainz match and must never be shown.
MODEL = [("Nas", "Illmatic"), ("Madvillain", "Madvillainy"), ("Kendrick Lamar", "To Pimp a Butterfly"),
         ("GZA", "Liquid Swords"), ("GZA/Genius", "Liquid Swords"), ("Burial", "Untrue"), ("Daft Punk", "Discovery"),
         ("Tame Impala", "Currents"), ("Frank Ocean", "Blonde"), ("Beyonce", "Lemonade"), ("Miles Davis", "Kind of Blue"),
         ("Radiohead", "OK Computer"), ("Radiohead", "In Rainbows"), ("Radiohead", "Kid A"), ("Radiohead", "Amnesiac"),
         ("Portishead", "Dummy"), ("Nobody", "Bootleg Tape"),
         ("Ol' Dirty Bastard", "Return to the 36 Chambers: The Dirty Version"),
         ("Drake", "Her Loss"),                          # credited only to the first artist: co-artist rule
         ("Pink Floyd", "Dark Side of the Moon"),        # no name match; its MBID wrongly points at a cover album
         ("Taylor Swift", "THE TORTURED POETS DEPARTMENT: THE ANTHOLOGY")]   # only its (valid) MBID matches
MBIDS = {("Pink Floyd", "Dark Side of the Moon"): rg_id("Dark Side of the Moon"),
         ("Taylor Swift", "THE TORTURED POETS DEPARTMENT: THE ANTHOLOGY"): rg_id("THE TORTURED POETS DEPARTMENT")}
# MusicBrainz merged an older duplicate of Amnesiac into it: the old id must keep resolving.
MERGED = {rg_id("Amnesiac (duplicate)"): "Amnesiac"}
CLUSTERS = {   # model indexes listened to together
    "hiphop": [0, 1, 2, 3, 4, 16],
    "rock": [11, 12, 13, 14, 15, 5],
    "electronic": [5, 6, 7, 15, 8, 9],
}


def _write_world(root) -> tuple[str, str]:
    model_dir, mb_dir = root / "model", root / "musicbrainz"
    model_dir.mkdir(), mb_dir.mkdir()
    con = duckdb.connect()
    _define_macros(con)
    keys = [con.execute("SELECT norm(?) || ' | ' || norm(strip_edition(?))", [a, t]).fetchone()[0] for a, t in MODEL]
    rng = np.random.default_rng(0)
    rows, user = [], 0
    for members in CLUSTERS.values():
        for _ in range(40):
            picks = rng.choice(members, size=4, replace=False)
            rows += [(user, int(a), r, int(rng.integers(10, 300))) for r, a in enumerate(picks, start=1)]
            user += 1
    inter = pd.DataFrame(rows, columns=["user_idx", "album_idx", "rank", "playcount"])
    n_users = inter.groupby("album_idx").size().reindex(range(len(MODEL)), fill_value=1)
    pd.DataFrame({"album_idx": range(len(MODEL)), "album_key": keys, "artist": [a for a, _ in MODEL],
                  "title": [t for _, t in MODEL],
                  "mbid": [MBIDS.get(m) for m in MODEL], "n_users": n_users.values, "total_plays": 100}
                 ).to_parquet(model_dir / "albums.parquet")
    inter.to_parquet(model_dir / "interactions.parquet")
    artists = sorted({n for a, _, _ in RELEASE_GROUPS for n in CREDITS.get(a, [a])})
    pd.DataFrame({"rg_mbid": [rg_id(t) for _, t, _ in RELEASE_GROUPS], "title": [t for _, t, _ in RELEASE_GROUPS],
                  "primary_type": "Album", "secondary_types": [SECONDARY.get(t, []) for _, t, _ in RELEASE_GROUPS],
                  "first_release_date": [OLDER.get(t, "1994-04-19") for _, t, _ in RELEASE_GROUPS], "artist_credit": [a for a, _, _ in RELEASE_GROUPS],
                  "artist_mbids": [[rg_id(n) for n in CREDITS.get(a, [a])] for a, _, _ in RELEASE_GROUPS], "genres": [g for _, _, g in RELEASE_GROUPS],
                  "rating": [RATINGS.get(t, (None, 0))[0] for _, t, _ in RELEASE_GROUPS],
                  "rating_votes": [RATINGS.get(t, (None, 0))[1] for _, t, _ in RELEASE_GROUPS]}
                 ).to_parquet(mb_dir / "release_groups.parquet")
    pd.DataFrame({"artist_mbid": [rg_id(a) for a in artists], "name": artists, "sort_name": artists,
                  "aliases": [ARTIST_ALIASES.get(a, []) for a in artists], "genres": [[] for _ in artists],
                  "country": [COUNTRIES.get(a) for a in artists], "type": "Group"}
                 ).to_parquet(mb_dir / "artists.parquet")
    # A minimal core dump: PostgreSQL COPY text, full width, \N for the columns ingest.catalog ignores.
    core = mb_dir / "core" / "mbdump"
    core.mkdir(parents=True)
    copy = lambda width, rows: "".join("\t".join([*map(str, r), *["\\N"] * (width - len(r))]) + "\n" for r in rows)
    internal = {t: i for i, (_, t, _) in enumerate(RELEASE_GROUPS, start=1)}
    (core / "release_group").write_text(copy(8, [(i, rg_id(t), t) for t, i in internal.items()]))
    (core / "artist_credit").write_text(copy(7, [(1, "Radiohead"), (2, "Portishead")]))
    (core / "release").write_text(copy(14, [(1, rg_id("Kid A release"), "Kid A", 1, internal["Kid A"]),
                                            (2, rg_id("Dummy release"), "Dummy", 2, internal["Dummy"]),
                                            *[(i, rg_id(f"Kid A release {i}"), "Kid A", 1, internal["Kid A"], 1) for i in (3, 4, 5)],
                                            (6, rg_id("OKNOTOK"), "OK Computer OKNOTOK 1997 2017", 1, internal["OK Computer"], 1)]))
    # Track lists (TRACKS): Kid A has a deluxe edition (3 + 1 bonus tracks, the oldest), a CD + DVD
    # edition and a digital one with 3 tracks each; the most common count wins, then the oldest, and
    # the DVD is left out. Dummy's only release is unofficial and has no medium format.
    (core / "medium_format").write_text(copy(8, [(1, "CD"), (2, "DVD"), (3, "Digital Media")]))
    (core / "medium").write_text(copy(9, [(10, 3, 1, 1, "", 0, 0, 3), (11, 3, 2, 1, "Bonus", 0, 0, 1),
                                          (12, 4, 1, 1, "", 0, 0, 3), (13, 4, 2, 2, "Videos", 0, 0, 2),
                                          (14, 5, 1, 3, "", 0, 0, 3), (20, 2, 1, "\\N", "", 0, 0, 2)]))
    track = lambda tid, medium, pos, title, credit=1, length=240000, data="f": (
        tid, rg_id(f"track {tid}"), tid, medium, pos, str(pos), title, credit, length, 0, 0, data)
    (core / "track").write_text(copy(12, [
        track(100, 10, 1, "Everything in Its Right Place"), track(101, 10, 2, "Kid A"), track(102, 10, 3, "The National Anthem"),
        track(103, 11, 1, "Bonus Jam"),
        track(110, 12, 1, "Everything in Its Right Place", length=251000), track(111, 12, 2, "Kid A", length="\\N"),
        track(112, 12, 3, "The National Anthem", credit=2), track(113, 12, 4, "Enhanced CD data", data="t"),
        track(120, 13, 1, "Music video"), track(121, 13, 2, "Interview"),
        track(130, 14, 1, "Everything in Its Right Place"), track(131, 14, 2, "Kid A"), track(132, 14, 3, "The National Anthem"),
        track(200, 20, 1, "Mysterons", credit=2), track(201, 20, 2, "Sour Times", credit=2)]))
    names = sorted({g for _, _, gs in RELEASE_GROUPS for g in gs} | {g for _, a, b in GENRE_LINKS for g in (a, b)})
    gid = {g: i for i, g in enumerate(names, start=1)}
    types = {"subgenre": 1095, "fusion of": 1096, "influenced by": 1097}
    (core / "genre").write_text(copy(6, [(i, rg_id(f"genre {g}"), g) for g, i in gid.items()]))
    (core / "link_type").write_text(copy(16, [(t, "\\N", 0, rg_id(n), "genre", "genre", n) for n, t in types.items()]
                                         + [(1, "\\N", 0, rg_id("other"), "artist", "genre", "subgenre")]))
    (core / "link").write_text(copy(11, [(9000 + t, t) for t in types.values()] + [(9001, 1)]))
    (core / "l_genre_genre").write_text(copy(9, [(i, 9000 + types[kind], gid[a], gid[b])
                                                 for i, (kind, a, b) in enumerate(GENRE_LINKS, start=1)]))
    # Streaming links (ADR 0016). Kid A: Spotify on release 3 (its deluxe edition: a bonus track) and on
    # release 4, the one its track list uses (4 wins); Apple only on the group, as an old itunes.apple.com
    # link. Dummy: only on its unofficial release. OK Computer: only on a reissue with another title, so
    # no regular link. A YouTube link and a Spotify artist link are ignored.
    urls = {1: "https://open.spotify.com/album/kidaOlder", 2: "https://open.spotify.com/album/kidaChosen?si=x",
            3: "https://itunes.apple.com/gb/album/kid-a/id1097862870", 4: "https://open.spotify.com/album/dummyAlbum",
            5: "https://www.youtube.com/watch?v=kida", 6: "https://open.spotify.com/artist/radiohead",
            7: "https://music.apple.com/jp/album/dummy/555", 8: "https://music.apple.com/us/album/kid-a-us/777",
            9: "https://open.spotify.com/album/oknotok"}
    (core / "url").write_text(copy(5, [(i, rg_id(u), u) for i, u in urls.items()]))
    # Apple: Kid A has a UK group link and a US link on release 5 (the US one wins: it works in every
    # store); Dummy only a Japanese one, which keeps its country.
    (core / "l_release_url").write_text(copy(9, [(1, 1, 3, 1), (2, 1, 4, 2), (3, 1, 2, 4), (4, 1, 4, 5), (5, 1, 4, 6),
                                                 (6, 1, 2, 7), (7, 1, 5, 8), (8, 1, 6, 9)]))
    (core / "l_release_group_url").write_text(copy(9, [(1, 1, internal["Kid A"], 3)]))
    (core / "release_group_gid_redirect").write_text(copy(3, [(old, internal[t], "2020-01-01") for old, t in MERGED.items()]))
    return str(model_dir), str(mb_dir)


@pytest.fixture(scope="session")
def world(tmp_path_factory):
    root = tmp_path_factory.mktemp("world")
    model_dir, mb_dir = _write_world(root)
    report = build(model_dir, mb_dir, str(root / "catalog.db"), log=lambda _: None)
    return {"model_dir": model_dir, "catalog": str(root / "catalog.db"), "report": report}


@pytest.fixture()
def database(tmp_path, monkeypatch):
    """A freshly migrated user database per test: a SQLite file, or the Postgres database named by
    INROTATION_TEST_DATABASE_URL (emptied with `alembic downgrade base` first, so never point it at real data)."""
    from alembic import command

    from app.db import _sessions, alembic_config, get_engine
    url = os.environ.get("INROTATION_TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("INROTATION_DATABASE_URL", url)
    get_engine.cache_clear(), _sessions.cache_clear()
    cfg = alembic_config(url)
    cfg.attributes["configure_logger"] = False
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield url
    get_engine().dispose()
    get_engine.cache_clear(), _sessions.cache_clear()


@pytest.fixture()
def client(world, database, monkeypatch, tmp_path):
    monkeypatch.setenv("INROTATION_COVERS", str(tmp_path / "covers"))
    monkeypatch.setenv("INROTATION_AVATARS", str(tmp_path / "avatars"))
    monkeypatch.setenv("INROTATION_MAP", str(tmp_path / "album_map.json"))   # never the real data/album_map.json
    monkeypatch.setenv("INROTATION_CATALOG", world["catalog"])
    monkeypatch.setenv("INROTATION_MODEL_DIR", world["model_dir"])
    from fastapi.testclient import TestClient

    from app.catalog import get_catalog
    from app.engine import get_engine
    from app.main import app

    get_catalog.cache_clear(), get_engine.cache_clear()
    with TestClient(app) as c:
        yield c
