import duckdb
import numpy as np
import pandas as pd
import pytest

from recs.matrix import build_user_album_matrix, l2_normalize_rows
from recs.preprocess import PreprocessConfig, _define_macros, run
from recs.probe_mbids import classify
from recs.synthetic import make_synthetic_db
from recs.weights import RANK_FUNCTIONS, WeightConfig, compute_weights, rank_score

A, A2, B, C = (
    "0136a543-33fa-4b80-a8ca-4a6094db3b71",
    "11111111-2222-4333-8444-555555555555",
    "c49af812-cb43-45ca-81e6-b81b7c287624",
    "267ae70d-6a82-4fd4-be60-d37bf25cde66",
)
ROWS = [
    (1, 1, "Visions", "Grimes", 100, A), (1, 2, "Blonde", "Frank Ocean", 90, B),
    (1, 3, "Lemonade", "Beyoncé", 80, C), (1, 4, "Untrue", "Burial", 70, ""),
    (1, 5, "Solo Album", "Lonely", 60, ""), (1, 0, "Bad Rank", "X", 50, ""),
    (2, 1, "Lemonade", "Beyonce", 300, ""), (2, 2, "Visions", "Grimes", 200, A),
    (2, 3, "Blonde", "Frank Ocean", 100, B), (2, 4, "Untrue", "Burial", 50, "not-a-uuid"),
    (2, 5, "Zero Plays", "Y", 0, ""),
    (3, 1, "Untrue", "Burial", 500, ""), (3, 2, "Visions (Deluxe Edition)", "Grimes", 400, A2),
    (3, 3, "Lemonade", "Beyoncé", 300, C), (3, 5, "Visions", "Grimes", 100, A),
    (3, 4, "", "Nobody", 10, ""), (3, 51, "Too Deep", "Z", 5, ""),
    (4, 1, "Blonde", "Frank Ocean", 70, B), (4, 2, "Untrue", "Burial", 60, ""),
    (4, 3, "Lemonade", "Beyoncé", 50, C),
]


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    d = tmp_path_factory.mktemp("pipe")
    db = str(d / "t.duckdb")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE user_top_albums (user_id INTEGER, rank INTEGER, album_name VARCHAR, artist_name VARCHAR, playcount BIGINT, mbid VARCHAR)")
    con.executemany("INSERT INTO user_top_albums VALUES (?, ?, ?, ?, ?, ?)", ROWS)
    con.close()
    out = d / "out"
    report = run(db, str(out), PreprocessConfig(min_album_users=2, min_user_albums=3))
    return report, pd.read_parquet(out / "albums.parquet"), pd.read_parquet(out / "interactions.parquet")


def test_report_counts_each_bad_row_once(result):
    report, _, _ = result
    assert report["raw"]["rows"] == 20
    assert report["dropped_rows"] == {
        "missing_user_id": 0, "missing_name": 1, "invalid_rank": 2,
        "invalid_playcount": 1, "empty_after_normalizing": 0,
    }
    assert report["valid_rows"] == 16
    assert report["mbid_state_of_valid_rows"]["malformed"] == 1


def test_editions_and_accents_collapse_to_one_album(result):
    _, albums, _ = result
    assert albums["title"].tolist() == ["Lemonade", "Untrue", "Blonde", "Visions"]
    assert albums.loc[0, "artist"] == "Beyoncé"            # most common spelling wins
    assert albums.loc[3, "mbid"] == A                       # most common ID, not the deluxe one's


def test_report_flags_edition_fragmentation(result):
    report, _, _ = result
    assert report["mbid"]["album_keys_with_several_mbids"] == 1
    assert report["rows_merged_within_user"] == 1


# (raw title, expected normalized title). Taken from conflicts seen in the real dataset.
TITLE_CASES = [
    ("Visions (Deluxe Edition)", "visions"),
    ("Born to Die - The Paradise Edition", "born to die"),
    ("Born to Die – Paradise Edition (Special Version)", "born to die"),
    ("Born to Die: The Paradise Edition", "born to die"),
    ("Born To Die (The Paradise Edit", "born to die"),
    ("Born to Die (Special Version)", "born to die"),
    ("In Utero - 20th Anniversary - Deluxe Edition", "in utero"),
    ("Turn On the Bright Lights: The Tenth Anniversary Edition (Remastered)", "turn on the bright lights"),
    ("Take Me Home: Yearbook Edition", "take me home"),
    ("Paramore: Self-Titled Deluxe", "paramore"),
    ("SOS Deluxe: LANA", "sos"),
    ("DAMN. COLLECTORS EDITION.", "damn"),
    ("Meteora 20th Anniversary Edition", "meteora"),
    ("The Velvet Underground & Nico 45th Anniversary", "the velvet underground nico"),
    ("From Under the Cork Tree Limited Tour Edition", "from under the cork tree"),
    ("The Wall - Disc 1", "the wall"),
    ("The Beatles (White Album) [Disc 2]", "the beatles white album"),
    ("The Fame Monster CD1", "the fame monster"),
    ("In Rainbows (Disk 2)", "in rainbows"),
    ("Erotica (PA Version)", "erotica"),
    ("Worship And Tribute (U.S. Version)", "worship and tribute"),
    ("Man on the Moon: The End of Day (Int'l Version)", "man on the moon the end of day"),
    # Different recordings or real titles: must stay apart.
    ("Red (Taylor's Version)", "red taylor s version"),
    ("Pet Sounds (Original Mono & Stereo Mix Versions)", "pet sounds original mono stereo mix versions"),
    ("Scaled and Icy (Livestream Version)", "scaled and icy livestream version"),
    ("Hellbilly Deluxe", "hellbilly deluxe"),
    ("Love Deluxe", "love deluxe"),
    ("Feel Special", "feel special"),
    ("Hello - Special Album", "hello special album"),
    ("THE TORTURED POETS DEPARTMENT: THE ANTHOLOGY", "the tortured poets department the anthology"),
    ("Mr. Morale & the Big Steppers", "mr morale the big steppers"),
    ("Jay-Z: Reasonable Doubt", "jay z reasonable doubt"),
]


@pytest.mark.parametrize("raw,expected", TITLE_CASES)
def test_edition_stripping_rules(raw, expected):
    con = duckdb.connect()
    _define_macros(con)
    assert con.execute("SELECT norm(strip_edition(?))", [raw]).fetchone()[0] == expected


def test_leftover_deluxe_folds_only_into_established_base(tmp_path):
    rows, uid = [], 0
    def listen(title, artist, users):
        nonlocal uid
        for _ in range(users):
            uid += 1
            rows.extend((uid, r, t, a, 10, "") for r, (t, a) in enumerate(
                [(title, artist), ("Filler A", "F"), ("Filler B", "F")], start=1))
    listen("Validation", "Shoreline Mafia", 12)
    listen("Validation Deluxe", "Shoreline Mafia", 5)
    listen("Hellbilly", "Rob Zombie", 2)            # truncated junk key, too small to absorb the real title
    listen("Hellbilly Deluxe", "Rob Zombie", 30)
    db = str(tmp_path / "f.duckdb")
    con = duckdb.connect(db)
    con.execute("CREATE TABLE user_top_albums (user_id INTEGER, rank INTEGER, album_name VARCHAR, artist_name VARCHAR, playcount BIGINT, mbid VARCHAR)")
    con.executemany("INSERT INTO user_top_albums VALUES (?, ?, ?, ?, ?, ?)", rows)
    con.close()
    report = run(db, str(tmp_path / "o"), PreprocessConfig(min_album_users=1, min_user_albums=1))
    keys = set(pd.read_parquet(tmp_path / "o" / "albums.parquet")["album_key"])
    assert "shoreline mafia | validation deluxe" not in keys and "rob zombie | hellbilly deluxe" in keys
    assert report["album_identity"]["keys_folded_into_base"] == 1


def test_sparse_album_and_short_users_filtered(result):
    report, albums, inter = result
    assert "Solo Album" not in albums["title"].tolist()
    assert report["kept"]["users"] == 4 and len(inter) == 14


def test_duplicate_editions_keep_best_rank_and_sum_plays(result):
    _, albums, inter = result
    visions = int(albums.index[albums["title"] == "Visions"][0])
    row = inter[(inter["user_idx"] == 2) & (inter["album_idx"] == visions)].iloc[0]   # user 3
    assert (row["rank"], row["playcount"]) == (2, 500)


def test_matrix_shape_and_weight_range(result):
    _, _, inter = result
    m = build_user_album_matrix(inter)
    assert m.shape == (4, 4) and m.nnz == 14
    assert m.data.min() > 0 and m.data.max() <= 1
    norms = np.sqrt(l2_normalize_rows(m).multiply(l2_normalize_rows(m)).sum(axis=1)).A1
    assert np.allclose(norms, 1.0, atol=1e-5)


@pytest.mark.parametrize("fn", sorted(RANK_FUNCTIONS))
def test_rank_functions_decrease_and_stay_positive(fn):
    s = rank_score(np.arange(1, 51), WeightConfig(rank_fn=fn))
    assert s[0] == pytest.approx(1.0) and np.all(np.diff(s) < 0) and s.min() > 0


def test_weights_blend_rank_and_play_count():
    df = pd.DataFrame({"user_idx": [0, 0, 1], "rank": [1, 2, 1], "playcount": [10, 1000, 5]})
    rank_only = compute_weights(df, WeightConfig(alpha=1.0))
    plays_only = compute_weights(df, WeightConfig(alpha=0.0))
    assert rank_only[0] > rank_only[1]
    assert plays_only[1] == pytest.approx(1.0) and plays_only[2] == pytest.approx(1.0)   # per-user max


def test_unknown_rank_function_rejected():
    with pytest.raises(ValueError):
        rank_score(np.array([1]), WeightConfig(rank_fn="nope"))


def test_probe_classify_uses_first_matching_kind():
    assert classify("x", lambda kind, _: 200 if kind == "release" else 404) == "release"
    assert classify("x", lambda kind, _: 404) == "unknown"


def test_synthetic_database_runs_through_pipeline(tmp_path):
    db = str(tmp_path / "s.duckdb")
    make_synthetic_db(db, n_users=300, n_albums=500, per_user=20)
    report = run(db, str(tmp_path / "o"), PreprocessConfig())
    assert report["kept"]["users"] > 0 and report["kept"]["interactions"] > 0
