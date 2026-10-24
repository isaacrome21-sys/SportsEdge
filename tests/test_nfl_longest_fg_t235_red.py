"""t235 RED-first regression tests (Grok ruling under owner delegation).

Earlier fix abc96e7e landed tests and fix in one commit; this file is
committed on its own BEFORE any fix. Ruling (consistent with the NBA combo
engine): a line must be a real number (int/float, numpy floats included),
never str/bool/None -> LONGEST_FG_LINE_INVALID. Before this, "44.5" and
" 44.5 " priced and True surfaced as OUT_OF_RANGE. Locks: np.int64 refused,
np.float64 prices identically, naive kickoff refused upstream.
Research only; nothing here is validated.
"""
from datetime import datetime

import numpy as np
import pytest

from sportsedge import nfl_longest_fg_empirical as eng
from test_nfl_longest_fg_empirical_20261022 import KO, games


@pytest.mark.parametrize("line", ["44.5", " 44.5 ", True, False, np.bool_(True), None, [44.5], b"44.5"])
def test_non_numeric_line_invalid(line):
    with pytest.raises(eng.NflLongestFgError) as e:
        eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO, line=line)
    assert str(e.value) == "LONGEST_FG_LINE_INVALID"


def test_np_int64_refused():
    with pytest.raises(eng.NflLongestFgError):
        eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO, line=np.int64(44))


def test_np_float64_same_as_float():
    a = eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO, line=np.float64(44.5))
    b = eng.price_longest_fg(games(), kicker_id="K1", kickoff=KO, line=44.5)
    assert a["p_made_longer_than_line"] == b["p_made_longer_than_line"]


def test_naive_kickoff_refused():
    with pytest.raises(eng.NflLongestFgError):
        eng.price_longest_fg(games(), kicker_id="K1", kickoff=datetime(2026, 10, 25, 17), line=44.5)


def test_line_max_still_prices():
    out = eng.price_longest_fg(games(atts=((49, True), (54, True), (60, True))),
                               kicker_id="K1", kickoff=KO, line=eng.LINE_MAX)
    assert 0.0 < out["p_made_longer_than_line"] < 1.0
