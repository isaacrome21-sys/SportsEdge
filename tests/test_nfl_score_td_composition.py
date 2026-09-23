import random
import pytest

from sportsedge.nfl_score_td_composition import (
    NflScoreTdCompositionError,
    attach_team_tds_to_score_paths,
    feasible_scoring_compositions,
    sample_td_count,
    team_game_states,
)


def test_every_composition_reconstructs_score_and_td_extras_do_not_exceed_tds():
    for score in range(0, 61):
        rows = feasible_scoring_compositions(score)
        assert rows
        for td, pat, two, fg, safety in rows:
            assert 6 * td + pat + 2 * two + 3 * fg + 2 * safety == score
            assert pat + two <= td


def test_not_score_div_seven_shortcut():
    # 9 can be TD+FG with a missed PAT or three FGs; the model retains both.
    rows = feasible_scoring_compositions(9)
    assert any(r[0] == 1 and r[3] == 1 for r in rows)
    assert any(r[0] == 0 and r[3] == 3 for r in rows)


def test_path_attachment_is_deterministic_and_preserves_scores():
    paths = [
        {"home_score": 27, "away_score": 20, "pace_multiplier": 1.04},
        {"home_score": 13, "away_score": 17, "pace_multiplier": .96},
        {"home_score": 0, "away_score": 3},
    ]
    a = attach_team_tds_to_score_paths(paths, seed=44)
    b = attach_team_tds_to_score_paths(paths, seed=44)
    assert a == b
    assert [(x["home_score"], x["away_score"]) for x in a] == [(27,20),(13,17),(0,3)]
    assert a[2]["home_team_tds"] == 0


def test_team_states_feed_same_margin_td_and_pace_path():
    rows = attach_team_tds_to_score_paths([
        {"home_score": 24, "away_score": 17, "pace_multiplier": 1.1},
        {"home_score": 10, "away_score": 20, "pace_multiplier": .9},
    ], seed=7)
    states = team_game_states(rows, team="home")
    assert [s["team_margin"] for s in states] == [7, -10]
    assert [s["team_tds"] for s in states] == [r["home_team_tds"] for r in rows]
    assert [s["pace_multiplier"] for s in states] == [1.1, .9]


def test_market_inputs_fail_closed():
    with pytest.raises(NflScoreTdCompositionError, match="MARKET_INPUT_FORBIDDEN"):
        attach_team_tds_to_score_paths([{"home_score": 21, "away_score": 17, "odds": -110}], seed=1)


def test_invalid_scores_fail_closed():
    with pytest.raises(NflScoreTdCompositionError, match="NONNEGATIVE_INTEGER"):
        attach_team_tds_to_score_paths([{"home_score": 21.5, "away_score": 17}], seed=1)
