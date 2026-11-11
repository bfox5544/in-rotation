import logging

import numpy as np
import pandas as pd
import pytest

from recs.evaluate import EvalConfig, evaluate, make_split, metrics
from recs.matrix import l2_normalize_rows
from recs.query import AlbumLookup, query_matrix, query_vector
from recs.recommender import (CosineSimilarity, NormalizedSum, PopularityRecommender, Recommender,
                              RecommenderConfig, WeightedSum)
from recs.weights import WeightConfig

HIT = 20   # album every user has: the popularity trap


def clustered(n_per_cluster=30, seed=0) -> pd.DataFrame:
    """Cluster A listens to albums 0-9, cluster B to 10-19, everyone to album 20."""
    rng = np.random.default_rng(seed)
    rows = []
    for u in range(2 * n_per_cluster):
        pool = np.arange(10) + (0 if u < n_per_cluster else 10)
        picks = [HIT, *rng.choice(pool, size=6, replace=False)]
        rows += [(u, a, r, int(rng.integers(5, 200))) for r, a in enumerate(picks, start=1)]
    return pd.DataFrame(rows, columns=["user_idx", "album_idx", "rank", "playcount"])


@pytest.fixture(scope="module")
def data():
    return clustered()


@pytest.fixture(scope="module")
def rec(data):
    return Recommender(RecommenderConfig(k=10)).fit(data, n_albums=21)


def test_plain_cosine_matches_normalized_dot_product(rec):
    Q = query_vector([0, 1, 2], 21)
    expected = (l2_normalize_rows(Q) @ l2_normalize_rows(rec.R).T).toarray()
    assert np.allclose(rec.similarity(Q), expected, atol=1e-6)


def test_asymmetric_cosine_formula(data):
    R = Recommender(RecommenderConfig()).fit(data, 21).R
    q = query_vector([0, 1], 21)
    sim = CosineSimilarity(asymmetry=0.75)
    sim.fit(R)
    r_norm = np.sqrt(R.multiply(R).sum(axis=1)).A1
    expected = (q @ R.T).toarray()[0] / (np.sqrt(2) ** 1.5 * r_norm ** 0.5)
    assert np.allclose(sim(q)[0], expected, atol=1e-6)


def test_neighbours_sorted_and_counted(rec):
    idx, sim = rec.neighbours(query_vector([0, 1, 2], 21), k=5)
    assert idx.shape == sim.shape == (1, 5)
    assert np.all(np.diff(sim[0]) <= 0)
    assert np.all(idx[0] < 30)   # all from cluster A


def test_cluster_query_gets_its_own_cluster_and_excludes_picks(rec):
    albums, scores = rec.recommend(query_vector([0, 1, 2], 21), n=8)
    assert not set(albums) & {0, 1, 2}
    assert set(albums[:6]) <= set(range(3, 10)) | {HIT}
    assert not set(albums) & set(range(10, 20))
    assert np.all(np.diff(scores) <= 0)


def test_extra_exclusions_and_rediscovery_flag(rec):
    q = query_vector([0, 1, 2], 21)
    assert HIT not in rec.recommend(q, n=10, exclude=np.array([HIT]))[0]
    assert {0, 1, 2} & set(rec.recommend(q, n=10, exclude_query=False)[0])


def test_aggregators_by_hand():
    from scipy import sparse
    R = sparse.csr_matrix(np.array([[1.0, 0.5], [0.0, 1.0]], np.float32))
    B = R.copy(); B.data[:] = 1
    N = sparse.csr_matrix(np.array([[0.5, 0.25]], np.float32))
    assert np.allclose(WeightedSum()(N, R, B), [[0.5, 0.5]])
    assert np.allclose(NormalizedSum(shrink=0.25)(N, R, B), [[0.5 / 0.75, 0.5 / 1.0]])


def test_popularity_dampener_demotes_the_hit(data):
    q = query_vector([0, 1, 2], 21)
    plain = Recommender(RecommenderConfig(k=10, pop_beta=0.0)).fit(data, 21)
    damped = plain.reconfigure(pop_beta=1.0)
    rank = lambda m: list(m.recommend(q, n=10)[0]).index(HIT)
    assert rank(damped) > rank(plain)


def test_reconfigure_shares_fit_and_rejects_refit_settings(rec):
    assert rec.reconfigure(k=3).R is rec.R
    with pytest.raises(ValueError):
        rec.reconfigure(weights=WeightConfig(alpha=1.0))
    with pytest.raises(ValueError):
        Recommender(RecommenderConfig(aggregator="nope"))


def test_empty_query_returns_empty_list(rec):
    albums, scores = rec.recommend(query_vector([], 21), n=5)
    assert len(albums) == 0 and len(scores) == 0


def test_popularity_baseline_skips_picks(data):
    pop = PopularityRecommender().fit(data, 21)
    out = pop.recommend_batch(query_matrix([[HIT], []], 21), n=3)
    assert HIT not in out[0] and out[1][0] == HIT and len(out[0]) == 3


def test_query_matrix_drops_unknown_and_keeps_max_weight(caplog):
    with caplog.at_level(logging.WARNING):
        Q = query_matrix([[1, 1, 99, -1]], 21, weights=[[0.3, 0.8, 1.0, 1.0]])
    assert Q.shape == (1, 21) and Q.nnz == 1 and Q[0, 1] == pytest.approx(0.8)
    assert "dropped 2" in caplog.text


def test_album_lookup_resolves_keys_and_mbids():
    albums = pd.DataFrame({"album_idx": [0, 1], "album_key": ["grimes | visions", "burial | untrue"],
                           "mbid": ["0136a543-33fa-4b80-a8ca-4a6094db3b71", None], "n_users": [5, 3]})
    found, missing = AlbumLookup(albums).resolve(["burial | untrue", "0136A543-33FA-4B80-A8CA-4A6094DB3B71", "nobody | nothing"])
    assert found == [1, 0] and missing == ["nobody | nothing"]


def test_metrics_by_hand():
    m = metrics([np.array([1, 2, 3])], [np.array([2, 9])], np.ones(10, np.float32), ks=(2,))
    assert m["precision@2"] == pytest.approx(0.5) and m["recall@2"] == pytest.approx(0.5)
    assert m["ndcg@2"] == pytest.approx((1 / np.log2(3)) / (1 + 1 / np.log2(3)))
    assert m["hit_rate@2"] == 1.0 and m["coverage@2"] == pytest.approx(0.2)


def test_split_hides_from_query_and_removes_eval_users_from_training(data):
    split = make_split(data, 21, EvalConfig(n_users=10, holdout=0.3, min_albums=5, seed=1))
    assert not set(split.users) & set(split.train["user_idx"])
    for i, u in enumerate(split.users):
        own = set(data.loc[data.user_idx == u, "album_idx"])
        picked = set(split.Q[i].indices)
        assert not picked & set(split.hidden[i]) and picked | set(split.hidden[i]) == own
        assert len(split.hidden[i]) == 2   # round(7 * 0.3)


def test_cf_beats_popularity_on_clustered_tastes():
    data = clustered(n_per_cluster=60, seed=3)
    ecfg = EvalConfig(n_users=40, holdout=0.3, min_albums=5, ks=(3,), seed=2)
    split = make_split(data, 21, ecfg)
    cf = evaluate(Recommender(RecommenderConfig(k=20)).fit(split.train, 21, split.n_users), split, ecfg)
    pop = evaluate(PopularityRecommender().fit(split.train, 21), split, ecfg)
    assert cf["ndcg@3"] > pop["ndcg@3"] + 0.1


def test_max_query_keeps_random_subset_and_same_hidden(data):
    full = make_split(data, 21, EvalConfig(n_users=10, holdout=0.3, min_albums=5, seed=4))
    short = make_split(data, 21, EvalConfig(n_users=10, holdout=0.3, min_albums=5, seed=4, max_query=2))
    assert all(np.array_equal(a, b) for a, b in zip(full.hidden, short.hidden))
    assert all(short.Q[i].nnz == 2 and set(short.Q[i].indices) <= set(full.Q[i].indices) for i in range(10))
    assert any(HIT not in short.Q[i].indices for i in range(10))   # not always the rank-1 album


def test_match_percentile_and_reference():
    import numpy as np
    from recs.match import percentile, reference
    scores = np.array([0.0, 1.0, 2.0, 3.0, 4.0, 5.0])
    support = np.array([0, 1, 2, 5, 3, 9])
    ref = reference(scores, support, exclude=np.array([5]))       # under 2 listeners or in the query: out
    assert list(ref) == [2.0, 3.0, 4.0]
    assert percentile(ref, 4.0) == 100 * 2.5 / 3 and percentile(ref, 10.0) == 100.0 and percentile(ref, 0.0) == 0.0
    assert percentile(np.array([]), 1.0) == 0.0
