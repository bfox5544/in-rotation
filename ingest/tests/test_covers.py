import sqlite3

from ingest.covers import image_path, known_missing, prefetch


def test_prefetch_fills_the_most_listened_first_and_skips_cached(tmp_path):
    db = tmp_path / "catalog.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE albums (id TEXT, popularity INTEGER)")
    con.executemany("INSERT INTO albums VALUES (?, ?)", [("aa-top", 300), ("bb-none", 200), ("cc-flaky", 100), ("dd-tail", 1)])
    con.commit()
    con.close()
    calls = []

    def fake(album_id):
        calls.append(album_id)
        if album_id == "cc-flaky":
            raise TimeoutError
        return None if album_id == "bb-none" else b"jpeg"

    root = tmp_path / "covers"
    counts = prefetch(str(db), top=3, workers=2, root=root, fetch=fake, log=lambda _: None)
    assert {k: counts[k] for k in ("fetched", "no_art", "failed")} == {"fetched": 1, "no_art": 1, "failed": 1}
    assert image_path("aa-top", root).read_bytes() == b"jpeg" and known_missing("bb-none", root)
    assert "dd-tail" not in calls                                    # outside the top 3
    calls.clear()
    again = prefetch(str(db), top=3, workers=2, root=root, fetch=fake, log=lambda _: None)
    assert calls == ["cc-flaky"] and again["already_cached"] == 2    # only the failure is retried
