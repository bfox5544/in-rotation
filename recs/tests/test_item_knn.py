"""The served item kNN model (recs.item_knn): ranking, similarity and the evidence behind a score."""
import numpy as np
import pytest

from recs.compare import ItemKNN as ComparedItemKNN
from recs.item_knn import ItemKNN
from recs.query import query_matrix, query_vector

from test_recommender import HIT, clustered

N = 21


@pytest.fixture(scope="module")
def model():
    return ItemKNN().fit(clustered(), N)


def test_recommends_the_query_cluster_and_never_the_query(model):
    albums, scores = model.recommend(query_vector([0, 1, 2], N), n=6)
    assert not {0, 1, 2} & set(albums)
    assert len(set(albums[:5]) - {HIT}) >= 4 and set(albums) - {HIT} <= set(range(10))
    assert np.all(np.diff(scores) <= 0)


def test_exclusions_and_reused_scores(model):
    q = query_vector([0, 1], N)
    scores = model.scores(q)[0]
    albums, _ = model.recommend(q, n=5, exclude=np.array([3, 4]), scores=scores)
    assert not {0, 1, 3, 4} & set(albums)
    assert model.scores(q)[0].tolist() == scores.tolist()      # the passed scores are not modified


def test_scores_are_summed_cosine_similarities(model):
    q = query_vector([0, 1], N, [1.0, 0.5])
    sim = model.similarity([0, 1], np.arange(N))
    assert np.allclose(model.scores(q)[0], sim[0] + 0.5 * sim[1], atol=1e-5)
    assert np.allclose(model.similarity([0], [0]), 1.0) and np.allclose(sim[0, 5], model.similarity([5], [0])[0, 0])


def test_same_ranking_as_the_compared_model(model):
    R = model.C   # any matrix: both normalize columns the same way
    compared = ComparedItemKNN().fit(R, model.popularity)
    Q = query_matrix([[0, 1, 2], [10, 11]], N)
    assert [list(r) for r in compared.recommend_batch(Q, 5)] == [list(r) for r in model.recommend_batch(Q, 5)]


def test_co_listeners_and_listeners(model):
    data = clustered()
    holders = set(data.loc[data.album_idx == 0, "user_idx"])
    assert set(model.listeners([0])) == holders
    counts = model.co_listeners(np.array([0]))
    assert counts[0] == len(holders) and counts[HIT] == len(holders)
    assert counts[15] == 0                                     # cluster B's albums share no listener with album 0


def test_diversify_keeps_the_order_at_zero_and_spreads_out_when_stronger(model):
    from recs.item_knn import diversify
    q = query_vector([0, 1, 10], N)                         # mostly cluster A, one album from cluster B
    scores = model.scores(q)[0]
    pool, _ = model.recommend(q, n=15, exclude=np.array([HIT]))   # the album everyone has is close to all
    assert list(diversify(model, pool, scores, 15, 0.0)) == list(pool)
    spread = diversify(model, pool, scores, 6, 0.7)
    assert spread[0] == pool[0] and set(spread) <= set(pool) and len(set(spread)) == 6
    b_side = lambda picks: sum(1 for a in picks if 10 <= a < 20)   # the cluster only one query album is from
    assert b_side(spread) > b_side(pool[:6])
