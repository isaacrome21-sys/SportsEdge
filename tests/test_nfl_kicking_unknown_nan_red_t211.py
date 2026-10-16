"""RED (t211u): kicking unknown outcomes and NaN thresholds fail closed."""
import math

import pandas as pd
import pytest

from sportsedge.nfl_kicking_empirical import (
    NflKickingError, build_kicking_games, prob_over_under)

PMF = {0: 0.25, 1: 0.5, 2: 0.25}


@pytest.mark.parametrize("line", [math.nan, math.inf, -math.inf, None, "1.5", True])
def test_nan_or_nonreal_threshold_refused(line):
    with pytest.raises(NflKickingError, match="KICKING_LINE_INVALID"):
        prob_over_under(PMF, line)


@pytest.mark.parametrize("pmf", [{0: math.nan, 1: 1.0}, {0: 0.5, 1: 0.6}, {}])
def test_invalid_pmf_refused_not_renormalised(pmf):
    with pytest.raises(NflKickingError, match="KICKING_PMF_INVALID"):
        prob_over_under(pmf, 0.5)


def test_valid_line_unchanged():
    assert prob_over_under(PMF, 1.5) == (0.25, 0.0, 0.75)


def _frames(fg_result="made", xp_result="good"):
    games = pd.DataFrame([{"game_id": "G1", "gameday": "2025-09-07",
                           "gametime": "13:00"}])
    pbp = pd.DataFrame([
        {"game_id": "G1", "kicker_player_id": "K1", "kicker_player_name": "K",
         "posteam": "CHI", "field_goal_attempt": 1, "field_goal_result": fg_result,
         "kick_distance": 40, "extra_point_attempt": 0, "extra_point_result": None},
        {"game_id": "G1", "kicker_player_id": "K1", "kicker_player_name": "K",
         "posteam": "CHI", "field_goal_attempt": 0, "field_goal_result": None,
         "kick_distance": None, "extra_point_attempt": 1,
         "extra_point_result": xp_result},
    ])
    return pbp, games


@pytest.mark.parametrize("res", [None, math.nan, "", "unknown", "MADE?"])
def test_unknown_fg_outcome_refused_not_counted_as_miss(res):
    with pytest.raises(NflKickingError, match="KICKING_FG_RESULT_UNKNOWN"):
        build_kicking_games(*_frames(fg_result=res))


@pytest.mark.parametrize("res", [None, math.nan, "", "unknown"])
def test_unknown_pat_outcome_refused_not_counted_as_miss(res):
    with pytest.raises(NflKickingError, match="KICKING_PAT_RESULT_UNKNOWN"):
        build_kicking_games(*_frames(xp_result=res))


@pytest.mark.parametrize("fg,xp", [("made", "good"), ("missed", "failed"),
                                   ("blocked", "blocked")])
def test_known_outcomes_still_build(fg, xp):
    rows = build_kicking_games(*_frames(fg, xp))
    assert rows[0]["fg_attempts"][0][1] is (fg == "made")
    assert rows[0]["pat_makes"] == (1 if xp == "good" else 0)
