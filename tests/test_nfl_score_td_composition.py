import random

import pytest

from sportsedge.nfl_score_td_composition import (
    NflScoreTdCompositionError,
    attach_team_tds_to_score_paths,
    feasible_scoring_compositions,
    sample_td_count,
    team_game_states,
)
from sportsedge.nfl_scoring_composition_fit import fit_scoring_composition_prior


def _row(score, touchdowns, extra_points_made=0, two_point_made=0, field_goals_made=0, safeties=0):
    return {
        "completed_at": "2026-09-20T20:00:00Z",
        "score": score,
        "touchdowns": touchdowns,
        "extra_points_made": extra_points_made,
        "two_point_made": two_point_made,
        "field_goals_made": field_goals_made,
        "safeties": safeties,
    }


def _prior():
    rows = [
        _row(27, 3, 3, field_goals_made=2),
        _row(20, 2, 2, field_goals_made=2),
        _row(13, 1, 1, field_goals_made=2),
        _row(17, 2, 2, field_goals_made=1),
        _row(0, 0),
        _row(3, 0, field_goals_made=1),
        _row(24, 3, 3, field_goals_made=1),
        _row(10, 1, 1, field_goals_made=1),
        _row(9, 1, field_goals_made=1),
        _row(9, 0, field_goals_made=3),
    ]
    return fit_scoring_composition_prior(rows, as_of="2026-09-23T12:00:00Z")


def test_feasible_compositions_reconstruct_scores_and_impossible_score_fails_closed():
    for score in range(0, 61):
        try:
            rows = feasible_scoring_compositions(score)
        except NflScoreTdCompositionError as exc:
            assert str(exc) == f"NO_FEASIBLE_SCORING_COMPOSITION:{score}"
            continue
        for td, pat, two, fg, safety in rows:
            assert 6 * td + pat + 2 * two + 3 * fg + 2 * safety == score
            assert pat + two <= td
    with pytest.raises(NflScoreTdCompositionError, match="NO_FEASIBLE_SCORING_COMPOSITION:1"):
        feasible_scoring_compositions(1)


def test_empirical_sampler_uses_only_fitted_exact_score_compositions():
    prior = _prior()
    rng = random.Random(31)
    draws = {sample_td_count(9, prior=prior, rng=rng) for _ in range(100)}
    assert draws == {0, 1}


def test_missing_fitted_score_has_no_invented_fallback():
    prior = _prior()
    with pytest.raises(NflScoreTdCompositionError, match="FITTED_SCORE_COMPOSITION_MISSING:21"):
        sample_td_count(21, prior=prior, rng=random.Random(1))


def test_path_attachment_is_deterministic_and_preserves_scores():
    prior = _prior()
    paths = [
        {"home_score": 27, "away_score": 20, "pace_multiplier": 1.04},
        {"home_score": 13, "away_score": 17, "pace_multiplier": .96},
        {"home_score": 0, "away_score": 3},
    ]
    a = attach_team_tds_to_score_paths(paths, prior=prior, seed=44)
    b = attach_team_tds_to_score_paths(paths, prior=prior, seed=44)
    assert a == b
    assert [(x["home_score"], x["away_score"]) for x in a] == [(27, 20), (13, 17), (0, 3)]
    assert a[2]["home_team_tds"] == 0


def test_team_states_feed_same_margin_td_and_pace_path():
    prior = _prior()
    rows = attach_team_tds_to_score_paths([
        {"home_score": 24, "away_score": 17, "pace_multiplier": 1.1},
        {"home_score": 10, "away_score": 20, "pace_multiplier": .9},
    ], prior=prior, seed=7)
    states = team_game_states(rows, team="home")
    assert [s["team_margin"] for s in states] == [7, -10]
    assert [s["team_tds"] for s in states] == [r["home_team_tds"] for r in rows]
    assert [s["pace_multiplier"] for s in states] == [1.1, .9]


def test_market_inputs_fail_closed():
    prior = _prior()
    with pytest.raises(NflScoreTdCompositionError, match="MARKET_INPUT_FORBIDDEN"):
        attach_team_tds_to_score_paths(
            [{"home_score": 24, "away_score": 17, "odds": -110}],
            prior=prior,
            seed=1,
        )


def test_invalid_scores_fail_closed():
    prior = _prior()
    with pytest.raises(NflScoreTdCompositionError, match="NONNEGATIVE_INTEGER"):
        attach_team_tds_to_score_paths(
            [{"home_score": 21.5, "away_score": 17}],
            prior=prior,
            seed=1,
        )
