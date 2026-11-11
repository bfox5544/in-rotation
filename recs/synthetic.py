"""Make a synthetic DuckDB file shaped like user_top_albums, for tests and timing.

    python -m recs.synthetic --out data/synthetic.duckdb --users 100000
"""
from __future__ import annotations

import argparse

import duckdb


def make_synthetic_db(path: str, n_users: int = 1000, n_albums: int = 5000, per_user: int = 50, seed: float = 0.42) -> None:
    con = duckdb.connect(path)
    con.execute(f"SELECT setseed({seed})")
    con.execute("DROP TABLE IF EXISTS user_top_albums")
    con.execute(f"""
        CREATE TABLE user_top_albums AS
        WITH picks AS (
            SELECT CAST(u AS INTEGER) AS user_id, k AS pick,
                   CAST(floor(pow(random(), 3) * {int(n_albums)}) AS INTEGER) AS album_id
            FROM range(1, {int(n_users)} + 1) t(u), range(0, {int(per_user)}) s(k)),
        dedup AS (SELECT user_id, album_id, min(pick) AS pick FROM picks GROUP BY ALL),
        ranked AS (SELECT user_id, album_id, CAST(row_number() OVER (PARTITION BY user_id ORDER BY pick) AS INTEGER) AS rank FROM dedup),
        shaped AS (SELECT *, md5('mb' || album_id) AS h FROM ranked)
        SELECT user_id, rank,
               'Album ' || album_id AS album_name,
               'Artist ' || (album_id // 5) AS artist_name,
               CAST(greatest(1, 300 // rank + floor(random() * 20)) AS BIGINT) AS playcount,
               CASE WHEN album_id % 5 = 0 THEN ''
                    ELSE substr(h,1,8)||'-'||substr(h,9,4)||'-'||substr(h,13,4)||'-'||substr(h,17,4)||'-'||substr(h,21,12) END AS mbid
        FROM shaped""")
    con.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--users", type=int, default=1000)
    p.add_argument("--albums", type=int, default=5000)
    a = p.parse_args()
    make_synthetic_db(a.out, a.users, a.albums)
    print(f"Wrote {a.out}")
