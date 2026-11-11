import io
import json
import tarfile

import pandas as pd

from ingest.musicbrainz import parse_release_group, run

DOC = {
    "id": "rg-1", "title": "Mel & George \"Do\" World War II", "primary-type": "Album", "secondary-types": ["Live"],
    "first-release-date": "1991-07-16",
    "artist-credit": [
        {"name": "George Shearing", "joinphrase": " & ", "artist": {"id": "a-1", "name": "George Shearing",
         "sort-name": "Shearing, George", "aliases": [{"name": "Дж. Шеринг"}], "genres": [{"name": "jazz", "count": 4}],
         "country": "GB", "type": "Person"}},
        {"name": "Mel Tormé", "joinphrase": "", "artist": {"id": "a-2", "name": "Mel Tormé", "sort-name": "Tormé, Mel",
         "aliases": [{"name": "Mel Torme"}, {"name": "Mel Torme"}], "genres": []}},
    ],
    "genres": [{"name": "vocal jazz", "count": 1}, {"name": "jazz", "count": 3}],
    "rating": {"value": 4.5, "votes-count": 2},
}


def test_parse_release_group_keeps_credit_order_and_ranks_genres():
    row, artists = parse_release_group(DOC)
    assert row["artist_credit"] == "George Shearing & Mel Tormé"
    assert row["artist_mbids"] == ["a-1", "a-2"] and row["genres"] == ["jazz", "vocal jazz"]
    assert row["secondary_types"] == ["Live"] and row["first_release_date"] == "1991-07-16"
    assert artists[1]["aliases"] == ["Mel Torme"] and artists[0]["genres"] == ["jazz"]
    assert row["rating"] == 4.5 and row["rating_votes"] == 2
    assert (artists[0]["country"], artists[0]["type"]) == ("GB", "Person") and artists[1]["country"] is None


def test_parse_tolerates_missing_fields():
    row, artists = parse_release_group({"id": "rg-2", "title": "Untitled"})
    assert row["artist_credit"] == "" and row["genres"] == [] and row["first_release_date"] is None and artists == []
    assert row["rating"] is None and row["rating_votes"] == 0


def test_run_reads_a_dump_shaped_archive(tmp_path):
    dump = tmp_path / "release-group.tar.xz"
    with tarfile.open(dump, "w:xz") as tar:
        for name, data in [("TIMESTAMP", b"2026-10-28 15:12:56+00\n"),
                           ("mbdump/release-group", (json.dumps(DOC) + "\n" + json.dumps({"id": "rg-2", "title": "B"}) + "\n").encode())]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    meta = run(str(dump), str(tmp_path / "out"), log=lambda _: None)
    assert meta == {"dump": "release-group.tar.xz", "timestamp": "2026-10-28 15:12:56+00", "release_groups": 2, "artists": 2}
    assert pd.read_parquet(tmp_path / "out" / "release_groups.parquet")["rg_mbid"].tolist() == ["rg-1", "rg-2"]
