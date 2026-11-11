import numpy as np
from scipy import sparse

from recs import album_map


def two_crowds(seed=0):
    """60 users who play albums 0-9 and 60 who play albums 10-19 (a few of each)."""
    rng = np.random.default_rng(seed)
    rows, cols = [], []
    for user in range(120):
        pool = range(0, 10) if user < 60 else range(10, 20)
        for a in rng.choice(list(pool), size=5, replace=False):
            rows.append(user), cols.append(int(a))
    return sparse.csr_matrix((np.ones(len(rows), np.float32), (rows, cols)), shape=(120, 20))


def test_album_vectors_sum_editions_and_normalize():
    m = sparse.csr_matrix(np.array([[1, 0, 2], [0, 3, 0]], np.float32))   # 2 users x 3 model albums
    v = album_map.album_vectors(m, [[0, 2], [1]]).toarray()
    assert np.allclose(v[0], [1, 0]) and np.allclose(v[1], [0, 1])       # albums 0 and 2 are one album


def test_layout_keeps_crowds_apart():
    v = album_map.album_vectors(two_crowds(), [[a] for a in range(20)])
    xy = album_map.layout(album_map.embed(v, dims=8), perplexity=5)
    assert xy.shape == (20, 2) and xy.min() >= 0 and xy.max() <= album_map.SIZE
    a, b = xy[:10], xy[10:]
    within = np.mean([np.linalg.norm(p - q) for p in a for q in a])
    across = np.mean([np.linalg.norm(p - q) for p in a for q in b])
    assert within < across / 2


def test_labels_sit_on_their_own_crowd_and_keep_apart():
    rng = np.random.default_rng(1)
    left = rng.normal([200, 500], 15, size=(40, 2))
    right = rng.normal([800, 500], 15, size=(40, 2))
    xy = np.vstack([left, right])
    labels = album_map.place_labels(xy, {"jazz": np.arange(40), "metal": np.arange(40, 80),
                                         "everything": np.arange(80), "tiny": np.arange(3)})
    by = {label["name"]: label for label in labels}
    assert set(by) == {"jazz", "metal"}           # "everything" never dominates a spot, "tiny" is too small
    assert abs(by["jazz"]["x"] - 200) < 50 and abs(by["metal"]["x"] - 800) < 50
    assert by["jazz"]["tier"] == by["metal"]["tier"] == 0


def test_close_labels_drop_to_a_later_tier_and_weights_settle_ties():
    xy = np.vstack([np.full((30, 2), 500.0), np.full((30, 2), 540.0)])
    labels = album_map.place_labels(xy, {"a": np.arange(30), "b": np.arange(30, 60)}, weight={"a": 0.5})
    assert [(label["name"], label["tier"]) for label in labels] == [("b", 0), ("a", 1)]
