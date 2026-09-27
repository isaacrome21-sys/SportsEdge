import pytest

from sportsedge.nfl_scoring_composition_fit import (
    NflScoringCompositionFitError,
    fit_scoring_composition_prior,
)


def row(**kw):
    base = {
        "completed_at": "2026-09-20T20:00:00Z",
        "score": 24,
        "touchdowns": 3,
        "extra_points_made": 3,
        "two_point_made": 0,
        "field_goals_made": 1,
        "safeties": 0,
    }
    base.update(kw)
    return base


def test_fit_counts_empirical_compositions_by_exact_score():
    prior = fit_scoring_composition_prior(
        [row(), row(), row(score=9, touchdowns=1, extra_points_made=0, field_goals_made=1)],
        as_of="2026-09-23T12:00:00Z",
    )
    assert prior.training_rows == 3
    assert prior.counts_by_score[24][(3, 3, 0, 1, 0)] == 2
    assert prior.counts_by_score[9][(1, 0, 0, 1, 0)] == 1


def test_future_or_same_time_training_row_fails_closed():
    with pytest.raises(NflScoringCompositionFitError, match="PIT_FUTURE"):
        fit_scoring_composition_prior(
            [row(completed_at="2026-09-23T12:00:00Z")],
            as_of="2026-09-23T12:00:00Z",
        )


def test_market_fields_cannot_enter_prior_fit():
    with pytest.raises(NflScoringCompositionFitError, match="MARKET_INPUT_FORBIDDEN"):
        fit_scoring_composition_prior(
            [row(odds=-110)], as_of="2026-09-23T12:00:00Z"
        )


def test_impossible_try_count_fails_closed():
    with pytest.raises(NflScoringCompositionFitError, match="POST_TD_TRIES_EXCEED"):
        fit_scoring_composition_prior(
            [row(touchdowns=1, extra_points_made=2, field_goals_made=4, score=20)],
            as_of="2026-09-23T12:00:00Z",
        )


def test_score_must_reconstruct_exactly():
    with pytest.raises(NflScoringCompositionFitError, match="DOES_NOT_RECONSTRUCT"):
        fit_scoring_composition_prior(
            [row(score=25)], as_of="2026-09-23T12:00:00Z"
        )
