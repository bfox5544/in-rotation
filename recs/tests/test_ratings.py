import numpy as np
import pytest

from recs.ratings import RATING_WEIGHTS, query_weight, stars_from_rank


def test_query_weight_follows_whole_and_half_stars():
    assert query_weight(5) == 1.0 and query_weight(3) == RATING_WEIGHTS[3] > 0
    assert query_weight(4.5) == pytest.approx((RATING_WEIGHTS[4] + RATING_WEIGHTS[5]) / 2)   # between whole stars
    assert query_weight(3) < query_weight(3.5) < query_weight(4) < query_weight(4.5) < query_weight(5)
    assert query_weight(2.5) == query_weight(0.5) == query_weight(None) == 0.0                 # "not for me"


def test_simulated_stars_from_rank():
    assert stars_from_rank(np.array([1, 10, 11, 25, 26, 50])).tolist() == [5, 5, 4, 4, 3, 3]
