"""Clean the user_top_albums table with DuckDB and write model-ready Parquet files.

    python -m recs.preprocess --db data/music.duckdb --out data/model

Outputs in --out:
    interactions.parquet  user_idx, album_idx, rank, playcount (one row per user and album)
    albums.parquet        album_idx, album_key, artist, title, mbid, n_users, total_plays
    report.json / report.md   data-quality report

Album identity is the normalized "artist | title" key with edition suffixes stripped,
so "Visions" and "Visions (Deluxe Edition)" count as one album. The MusicBrainz ID is
kept as an attribute (the most common one per album), because it may be a release ID,
and different editions of one album then carry different IDs.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb

UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
EDITION_WORDS = r"deluxe|remaster(?:ed)?|expanded|anniversary|bonus|collector'?s?|limited|reissue|explicit|clean|edition"
# Release variants of the same recordings. "Taylor's Version", "Live Version" and "Mix Versions" are not here.
VERSIONS = r"(?:special|standard|international|int'l|u\.?s\.?|uk|pa|latam|extended|dirty|double disc)\s+version"
DISC = r"(?:dis[ck]|cd)\s*\d+"
TAG = rf"(?:{EDITION_WORDS}|{VERSIONS}|{DISC})"

# strip_edition applies these in order (pattern, replacement, flags). The first step turns
# " - ", " – ", " — ", " ~ " and ": " into one " | " marker so later steps see one separator.
STRIP_STEPS = [
    (r"\s+[-–—~]\s+|\s*:\s+", " | ", "g"),
    (rf"\s*[\(\[][^\)\]]*\b{TAG}\b[^\)\]]*[\)\]]", "", "gi"),   # "Visions (Deluxe Edition)", "[Disc 1]"
    (r"\s+[\(\[][^\)\]]*$", "", ""),                              # truncated "Born To Die (The Paradise Edit"
    (rf"\s+\|\s+[^|]*\b{TAG}\b[^|]*$", "", "i"),                  # "Bleach: Deluxe Edition", "Born to Die – Paradise Edition"
    (rf"\s+\|\s+[^|]*\b{TAG}\b[^|]*$", "", "i"),                  # again, for "In Utero - 20th Anniversary - Deluxe Edition"
    (r"\s+(?:deluxe|edition)\s+\|.*$", "", "i"),                  # "SOS Deluxe: LANA"
    # Bare suffixes, only with unambiguous wording: "Hellbilly Deluxe" and "Love Deluxe" are real titles.
    (r"\s+(?:(?:the\s+)?(?:(?:super\s+)?deluxe|special|limited(?:\s+tour)?|collector'?s?|platinum|expanded"
     rf"|(?:\d+(?:st|nd|rd|th)\s+)?anniversary)\s+(?:edition|version)|\d+(?:st|nd|rd|th)\s+anniversary|{DISC})\W*$", "", "i"),
]

# A normalized title ending in "deluxe" or "edition" that the rules above left alone ("Validation Deluxe",
# "Born To Die Paradise Edition") joins the same artist's shorter key if that key is established:
# at least MIN_BASE_USERS listeners and BASE_SHARE of the variant's. This keeps "Hellbilly Deluxe" apart
# from a 2-listener truncated "Hellbilly".
MIN_BASE_USERS = 10
BASE_SHARE = 0.1


@dataclass(frozen=True)
class PreprocessConfig:
    max_rank: int = 50
    min_album_users: int = 2   # albums with fewer listeners can't link users together
    min_user_albums: int = 5   # users with fewer albums give weak similarity signals


def _sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _define_macros(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        "CREATE OR REPLACE MACRO norm(s) AS "
        r"trim(regexp_replace(lower(strip_accents(s)), '[^\p{L}\p{N}]+', ' ', 'g'))"
    )
    expr = "s"
    for pattern, repl, flags in STRIP_STEPS:
        opts = f", {_sql_str(flags)}" if flags else ""
        expr = f"regexp_replace({expr}, {_sql_str(pattern)}, {_sql_str(repl)}{opts})"
    con.execute(f"CREATE OR REPLACE MACRO strip_edition(s) AS trim({expr})")


def _one(con: duckdb.DuckDBPyConnection, sql: str):
    return con.execute(sql).fetchone()


def run(db_path: str, out_dir: str, cfg: PreprocessConfig = PreprocessConfig(),
        memory_limit: str | None = None, temp_dir: str | None = None) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(":memory:")
    if memory_limit:
        con.execute(f"SET memory_limit={_sql_str(memory_limit)}")
    if temp_dir:
        con.execute(f"SET temp_directory={_sql_str(temp_dir)}")
    con.execute(f"ATTACH {_sql_str(db_path)} AS src (READ_ONLY)")
    _define_macros(con)
    max_rank, min_au, min_ua = int(cfg.max_rank), int(cfg.min_album_users), int(cfg.min_user_albums)

    report: dict = {"config": asdict(cfg)}
    raw_rows, raw_users = _one(con, "SELECT count(*), count(DISTINCT user_id) FROM src.user_top_albums")
    report["raw"] = {"rows": raw_rows, "users": raw_users}

    # 1. Validate. Each bad row is counted once, under the first rule it breaks.
    reasons = con.execute(f"""
        SELECT CASE
                 WHEN user_id IS NULL THEN 'missing_user_id'
                 WHEN coalesce(trim(album_name), '') = '' OR coalesce(trim(artist_name), '') = '' THEN 'missing_name'
                 WHEN rank IS NULL OR rank < 1 OR rank > {max_rank} THEN 'invalid_rank'
                 WHEN playcount IS NULL OR playcount <= 0 THEN 'invalid_playcount'
               END AS reason, count(*)
        FROM src.user_top_albums GROUP BY 1""").fetchall()
    dropped = {r: n for r, n in reasons if r is not None}
    report["dropped_rows"] = {k: dropped.get(k, 0) for k in
                              ("missing_user_id", "missing_name", "invalid_rank", "invalid_playcount")}

    con.execute(f"""
        CREATE TEMP TABLE valid AS
        SELECT user_id, rank, trim(album_name) AS album_name, trim(artist_name) AS artist_name, playcount,
               CASE WHEN coalesce(trim(mbid), '') = '' THEN 'blank'
                    WHEN regexp_matches(lower(trim(mbid)), '{UUID_RE}') THEN 'valid'
                    ELSE 'malformed' END AS mbid_state,
               CASE WHEN regexp_matches(lower(trim(mbid)), '{UUID_RE}') THEN lower(trim(mbid)) END AS mbid
        FROM src.user_top_albums
        WHERE user_id IS NOT NULL
          AND coalesce(trim(album_name), '') <> '' AND coalesce(trim(artist_name), '') <> ''
          AND rank BETWEEN 1 AND {max_rank} AND playcount > 0""")
    valid_rows = _one(con, "SELECT count(*) FROM valid")[0]
    report["valid_rows"] = valid_rows
    report["mbid_state_of_valid_rows"] = {s: n for s, n in con.execute(
        "SELECT mbid_state, count(*) FROM valid GROUP BY 1").fetchall()}
    for s in ("blank", "valid", "malformed"):
        report["mbid_state_of_valid_rows"].setdefault(s, 0)

    # 2. Normalize names and build the album key.
    con.execute("""
        CREATE TEMP TABLE keyed AS
        SELECT *, artist_norm || ' | ' || title_norm AS album_key FROM (
            SELECT *, norm(artist_name) AS artist_norm,
                   CASE WHEN norm(strip_edition(album_name)) <> '' THEN norm(strip_edition(album_name))
                        ELSE norm(album_name) END AS title_norm
            FROM valid)
        WHERE artist_norm <> '' AND title_norm <> ''""")
    keyed_rows = _one(con, "SELECT count(*) FROM keyed")[0]
    report["dropped_rows"]["empty_after_normalizing"] = valid_rows - keyed_rows

    # 2b. Fold leftover "... deluxe" / "... edition" keys into an established base key (see MIN_BASE_USERS).
    con.execute("CREATE TEMP TABLE key_users AS SELECT artist_norm, title_norm, count(DISTINCT user_id) n FROM keyed GROUP BY 1, 2")
    con.execute(rf"""
        CREATE TEMP TABLE base_remap AS
        WITH cands AS (
            SELECT artist_norm, title_norm, n, unnest([
                regexp_replace(title_norm, ' deluxe$', ''), regexp_replace(title_norm, ' edition$', ''),
                regexp_replace(title_norm, ' \S+ edition$', ''), regexp_replace(title_norm, ' \S+ \S+ edition$', '')]) AS base
            FROM key_users WHERE regexp_matches(title_norm, ' (deluxe|edition)$'))
        SELECT c.artist_norm, c.title_norm, arg_max(c.base, b.n) AS base
        FROM cands c JOIN key_users b ON b.artist_norm = c.artist_norm AND b.title_norm = c.base
        WHERE c.base <> c.title_norm AND b.n >= greatest({MIN_BASE_USERS}, {BASE_SHARE} * c.n)
        GROUP BY 1, 2""")
    con.execute("""
        UPDATE keyed SET title_norm = r.base, album_key = keyed.artist_norm || ' | ' || r.base
        FROM base_remap r WHERE keyed.artist_norm = r.artist_norm AND keyed.title_norm = r.title_norm""")
    raw_pairs, keys = _one(con, "SELECT count(DISTINCT (artist_name, album_name)), count(DISTINCT album_key) FROM keyed")
    report["album_identity"] = {"distinct_raw_artist_title_pairs": raw_pairs, "distinct_album_keys": keys,
                                "keys_folded_into_base": _one(con, "SELECT count(*) FROM base_remap")[0]}

    # 3. MBID diagnostics.
    con.execute("CREATE TEMP TABLE mbid_counts AS SELECT album_key, mbid, count(*) c FROM keyed WHERE mbid IS NOT NULL GROUP BY ALL")
    report["mbid"] = {
        "distinct_valid_mbids": _one(con, "SELECT count(DISTINCT mbid) FROM mbid_counts")[0],
        "mbids_shared_by_several_album_keys": _one(con, "SELECT count(*) FROM (SELECT mbid FROM mbid_counts GROUP BY mbid HAVING count(DISTINCT album_key) > 1)")[0],
        "album_keys_with_several_mbids": _one(con, "SELECT count(*) FROM (SELECT album_key FROM mbid_counts GROUP BY album_key HAVING count(*) > 1)")[0],
        "album_keys_with_no_mbid": _one(con, "SELECT count(*) FROM (SELECT DISTINCT album_key FROM keyed) WHERE album_key NOT IN (SELECT album_key FROM mbid_counts)")[0],
    }

    # 4. One row per user and album: best rank, summed plays (covers duplicates and merged editions).
    con.execute("""
        CREATE TEMP TABLE merged AS
        SELECT user_id, album_key, min(rank) AS rank, CAST(sum(playcount) AS BIGINT) AS playcount
        FROM keyed GROUP BY user_id, album_key""")
    merged_rows = _one(con, "SELECT count(*) FROM merged")[0]
    report["rows_merged_within_user"] = keyed_rows - merged_rows

    # 5. Filter sparse albums, then short user lists (one pass; see docs).
    con.execute("CREATE TEMP TABLE album_users AS SELECT album_key, count(*) n FROM merged GROUP BY 1")
    report["album_popularity_before_filter"] = dict(zip(
        ("albums", "with_1_user", "with_2_to_9_users", "with_10_plus_users"),
        _one(con, "SELECT count(*), count(*) FILTER (WHERE n = 1), count(*) FILTER (WHERE n BETWEEN 2 AND 9), count(*) FILTER (WHERE n >= 10) FROM album_users")))
    con.execute(f"""
        CREATE TEMP TABLE m1 AS SELECT m.* FROM merged m
        JOIN album_users a USING (album_key) WHERE a.n >= {min_au}""")
    con.execute(f"""
        CREATE TEMP TABLE kept_users AS SELECT user_id FROM m1 GROUP BY user_id HAVING count(*) >= {min_ua}""")
    con.execute("CREATE TEMP TABLE m2 AS SELECT m1.* FROM m1 JOIN kept_users USING (user_id)")

    # 6. Dense indexes: popular albums get low album_idx.
    con.execute("""
        CREATE TEMP TABLE album_stats AS
        SELECT album_key, count(*) AS n_users, CAST(sum(playcount) AS BIGINT) AS total_plays FROM m2 GROUP BY 1""")
    con.execute("CREATE TEMP TABLE album_idx AS SELECT album_key, n_users, total_plays, CAST(row_number() OVER (ORDER BY n_users DESC, album_key) - 1 AS INTEGER) AS album_idx FROM album_stats")
    con.execute("CREATE TEMP TABLE user_idx AS SELECT user_id, CAST(row_number() OVER (ORDER BY user_id) - 1 AS INTEGER) AS user_idx FROM kept_users")
    con.execute("CREATE TEMP TABLE names AS SELECT album_key, artist_name, album_name, count(*) c FROM keyed GROUP BY ALL")
    con.execute("CREATE TEMP TABLE display AS SELECT album_key, arg_max(artist_name, c) AS artist, arg_max(album_name, c) AS title FROM names GROUP BY 1")
    con.execute("CREATE TEMP TABLE best_mbid AS SELECT album_key, arg_max(mbid, c) AS mbid FROM mbid_counts GROUP BY 1")

    interactions = out / "interactions.parquet"
    albums = out / "albums.parquet"
    con.execute(f"""COPY (SELECT u.user_idx, a.album_idx, CAST(m.rank AS INTEGER) AS rank, m.playcount
                          FROM m2 m JOIN user_idx u USING (user_id) JOIN album_idx a USING (album_key)
                          ORDER BY u.user_idx, m.rank) TO {_sql_str(str(interactions))} (FORMAT PARQUET)""")
    con.execute(f"""COPY (SELECT a.album_idx, a.album_key, d.artist, d.title, b.mbid, a.n_users, a.total_plays
                          FROM album_idx a JOIN display d USING (album_key) LEFT JOIN best_mbid b USING (album_key)
                          ORDER BY a.album_idx) TO {_sql_str(str(albums))} (FORMAT PARQUET)""")

    # 7. Summary of what was kept.
    n_int, n_users, n_albums = _one(con, "SELECT (SELECT count(*) FROM m2), (SELECT count(*) FROM user_idx), (SELECT count(*) FROM album_idx)")
    lo, med, p95, hi = _one(con, "SELECT min(n), quantile_cont(n, 0.5), quantile_cont(n, 0.95), max(n) FROM (SELECT count(*) n FROM m2 GROUP BY user_id)") if n_int else (0, 0, 0, 0)
    report["kept"] = {
        "users": n_users, "albums": n_albums, "interactions": n_int,
        "density": (n_int / (n_users * n_albums)) if n_users and n_albums else 0.0,
        "albums_per_user": {"min": lo, "median": med, "p95": p95, "max": hi},
        "users_removed": raw_users - n_users,
        "rows_removed_by_album_filter": merged_rows - _one(con, "SELECT count(*) FROM m1")[0],
        "rows_removed_by_user_filter": _one(con, "SELECT count(*) FROM m1")[0] - n_int,
    }
    report["top_albums"] = [
        {"title": t, "artist": a, "users": n}
        for t, a, n in con.execute("SELECT d.title, d.artist, a.n_users FROM album_idx a JOIN display d USING (album_key) ORDER BY a.album_idx LIMIT 10").fetchall()
    ]
    con.close()

    (out / "report.json").write_text(json.dumps(report, indent=2, default=float), encoding="utf-8")
    (out / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def render_markdown(r: dict) -> str:
    pct = lambda n, d: f"{100 * n / d:.1f}%" if d else "n/a"
    v, m, k = r["valid_rows"], r["mbid"], r["kept"]
    st = r["mbid_state_of_valid_rows"]
    lines = [
        "# Data-quality report", "",
        f"Raw: {r['raw']['rows']:,} rows from {r['raw']['users']:,} users. Valid rows: {v:,}.", "",
        "## Dropped rows", *[f"- {name.replace('_', ' ')}: {n:,}" for name, n in r["dropped_rows"].items()], "",
        "## MusicBrainz IDs (valid rows)",
        f"- blank: {st['blank']:,} ({pct(st['blank'], v)}); malformed: {st['malformed']:,}; usable: {st['valid']:,} ({pct(st['valid'], v)})",
        f"- distinct usable IDs: {m['distinct_valid_mbids']:,}",
        f"- album keys with no ID: {m['album_keys_with_no_mbid']:,}",
        f"- album keys carrying several IDs: {m['album_keys_with_several_mbids']:,} (suggests IDs are per release, not per album)",
        f"- IDs shared by several album keys: {m['mbids_shared_by_several_album_keys']:,}", "",
        "## Album identity",
        f"- distinct raw artist/title pairs: {r['album_identity']['distinct_raw_artist_title_pairs']:,}",
        f"- distinct album keys after normalizing and stripping editions: {r['album_identity']['distinct_album_keys']:,}",
        f"- \"... deluxe\" / \"... edition\" keys folded into an established base key: {r['album_identity']['keys_folded_into_base']:,}",
        f"- rows merged because one user had the same album twice: {r['rows_merged_within_user']:,}", "",
        "## Album popularity before filtering",
        *[f"- {name.replace('_', ' ')}: {n:,}" for name, n in r["album_popularity_before_filter"].items()], "",
        f"## Kept (min {r['config']['min_album_users']} listeners per album, min {r['config']['min_user_albums']} albums per user)",
        f"- users: {k['users']:,}; albums: {k['albums']:,}; interactions: {k['interactions']:,}; density: {k['density']:.5f}",
        f"- albums per user: min {k['albums_per_user']['min']}, median {k['albums_per_user']['median']:.0f}, p95 {k['albums_per_user']['p95']:.0f}, max {k['albums_per_user']['max']}",
        f"- removed by album filter: {k['rows_removed_by_album_filter']:,} rows; by user filter: {k['rows_removed_by_user_filter']:,} rows; users lost: {k['users_removed']:,}", "",
        "## Most-listened albums kept",
        *[f"- {a['title']} by {a['artist']} ({a['users']:,} users)" for a in r["top_albums"]], "",
    ]
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="DuckDB file containing user_top_albums")
    p.add_argument("--out", default="data/model")
    p.add_argument("--max-rank", type=int, default=PreprocessConfig.max_rank)
    p.add_argument("--min-album-users", type=int, default=PreprocessConfig.min_album_users)
    p.add_argument("--min-user-albums", type=int, default=PreprocessConfig.min_user_albums)
    p.add_argument("--memory-limit", help="e.g. 8GB (DuckDB spills to disk beyond this)")
    p.add_argument("--temp-dir", help="spill directory for DuckDB")
    a = p.parse_args()
    rep = run(a.db, a.out, PreprocessConfig(a.max_rank, a.min_album_users, a.min_user_albums), a.memory_limit, a.temp_dir)
    print(render_markdown(rep))
    print(f"Wrote files to {a.out}")


if __name__ == "__main__":
    main()
