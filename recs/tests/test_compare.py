"""The model comparison (run 6): every family recommends sensibly on clustered data, through one interface."""
import numpy as np
import pytest

from recs.compare import ALS, ItemKNN, Popularity, PureSVD, RP3Beta, UserKNN, per_user_ndcg, shared_matrix
from recs.evaluate import EvalConfig, make_split, metrics
from recs.query import query_matrix

from test_recommender import HIT, clustered

CLUSTER_A = set(range(10))


@pytest.fixture(scope="module")
def split():
    return make_split(clustered(), 21, EvalConfig(n_users=10, min_albums=5, seed=3))


@pytest.fixture(scope="module")
def shared(split):
    return shared_matrix(split)


FAMILIES = [lambda: ItemKNN(), lambda: RP3Beta(), lambda: PureSVD(k=4), lambda: ItemKNN(beta=0.5)]


@pytest.mark.parametrize("make", FAMILIES)
def test_each_family_recommends_the_query_cluster_and_never_the_query(make, split, shared):
    R, pop = shared
    model = make().fit(R, pop)
    Q = query_matrix([[0, 1, 2]], 21)
    top = model.recommend_batch(Q, 5)[0]
    assert len(top) == 5 and not {0, 1, 2} & set(top)
    assert len(set(top[:4]) & CLUSTER_A) >= 3        # the rest of cluster A, not cluster B


def test_popularity_adjustment_moves_the_hit_down(split, shared):
    R, pop = shared
    Q = query_matrix([[0, 1, 2]], 21)
    plain = list(ItemKNN(0.0).fit(R, pop).recommend_batch(Q, 10)[0])
    damped = list(ItemKNN(1.0).fit(R, pop).recommend_batch(Q, 10)[0])
    assert damped.index(HIT) > plain.index(HIT)


def test_popularity_ignores_the_query_except_to_exclude_it(split, shared):
    R, pop = shared
    top = Popularity().fit(R, pop).recommend_batch(query_matrix([[HIT]], 21), 3)[0]
    assert HIT not in top and pop[top[0]] == pop[top].max()


def test_als_folds_a_new_listener_into_their_cluster(split, shared):
    pytest.importorskip("implicit")
    R, pop = shared
    model = ALS(factors=4, alpha=10.0, iterations=10).fit(R, pop)
    top = model.recommend_batch(query_matrix([[10, 11, 12]], 21), 4)[0]
    assert len(set(top) & set(range(10, 20))) >= 3


def test_user_knn_is_the_served_engine(split):
    model = UserKNN(k=10, beta=0.0).fit_split(split)
    recs = model.recommend_batch(split.Q, 5)
    assert len(recs) == len(split.users) and all(len(r) <= 5 for r in recs)


def test_per_user_ndcg_averages_to_the_shared_metric(split, shared):
    R, pop = shared
    recs = ItemKNN().fit(R, pop).recommend_batch(split.Q, 20)
    assert np.isclose(per_user_ndcg(recs, split.hidden).mean(), metrics(recs, split.hidden, pop, (20,))["ndcg@20"])
