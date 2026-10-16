"""RED (t212 audit): kicking pmf keys must be finite non-negative integers,
NaN attempt flags are named refusals, numpy integer lines are accepted."""
import math

import numpy as np
import pandas as pd
import pytest

from sportsedge.nfl_kicking_empirical import (
    NflKickingError, build_kicking_games, prob_over_under)
from test_nfl_kicking_unknown_nan_red_t211 import _frames


@pytest.mark.parametrize("pmf", [
    {0: 0.5, math.nan: 0.5},
    {0: 0.5, None: 0.5},
    {0: 0.5, "1": 0.5},
    {0: 0.5, -1: 0.5},
    {0: 0.5, 1.5: 0.5},
    {0: 0.5, math.inf: 0.5},
    {0: 0.5, True: 0.5},
])
def test_bad_pmf_keys_refused_named(pmf):
    with pytest.raises(NflKickingError, match="KICKING_PMF_KEY_INVALID"):
        prob_over_under(pmf, 0.5)


def test_numpy_integer_keys_and_lines_accepted():
    pmf = {np.int64(0): 0.25, np.int64(1): 0.5, np.int64(2): 0.25}
    assert prob_over_under(pmf, np.int64(1)) == (0.25, 0.5, 0.25)
    assert prob_over_under({0: 0.25, 1: 0.5, 2: 0.25}, np.int32(1)) == (0.25, 0.5, 0.25)
    assert prob_over_under({0: 0.25, 1: 0.5, 2: 0.25}, np.float64(1.5)) == (0.25, 0.0, 0.75)


@pytest.mark.parametrize("col", ["field_goal_attempt", "extra_point_attempt"])
@pytest.mark.parametrize("bad", [math.nan, None, "x", 2])
def test_nan_or_invalid_attempt_flag_refused_named(col, bad):
    pbp, games = _frames()
    pbp[col] = pbp[col].astype(object)
    pbp.loc[0 if col == "field_goal_attempt" else 1, col] = bad
    with pytest.raises(NflKickingError, match=f"KICKING_ATTEMPT_FLAG_INVALID:{col}"):
        build_kicking_games(pbp, games)
