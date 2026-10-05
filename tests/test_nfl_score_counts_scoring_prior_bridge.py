from datetime import datetime, timezone

import pytest

from sportsedge.sports.nfl.score_counts_scoring_prior_bridge import (
    ScoreCountScoringPriorBridgeError,
    fit_scoring_prior_from_score_count_training_rows,
    score_count_training_rows_to_composition_rows,
)


def _row(**overrides):
    row = {
        "game_start_ts": "2025-09-07T17:00:00+00:00",
        "offense_touchdowns": 3,
        "def_st_touchdowns": 0,
        "pat_made": 3,
        "two_point_made": 0,
        "made_field_goals": 1,
        "safeties": 0,
    }
    row.update(overrides)
    return row


def test_projects_exact_scoring_components_without_market_fields():
    rows = score_count_training_rows_to_composition_rows([_row()])
    assert rows == [{
        "completed_at": "2025-09-08T17:00:00+00:00",
        "touchdowns": 3,
        "extra_points_made": 3,
        "two_point_made": 0,
        "field_goals_made": 1,
        "safeties": 0,
        "score": 24,
    }]


def test_def_st_touchdowns_are_included_in_team_td_total():
    rows = score_count_training_rows_to_composition_rows([
        _row(offense_touchdowns=2, def_st_touchdowns=1, pat_made=3, made_field_goals=0)
    ])
    assert rows[0]["touchdowns"] == 3
    assert rows[0]["score"] == 21


def test_fits_existing_scoring_composition_prior_contract():
    prior = fit_scoring_prior_from_score_count_training_rows(
        [
            _row(),
            _row(
                game_start_ts="2025-09-14T17:00:00+00:00",
                offense_touchdowns=2,
                pat_made=2,
                made_field_goals=1,
            ),
        ],
        as_of=datetime(2026, 10, 9, tzinfo=timezone.utc),
    )
    assert prior.training_rows == 2
    assert prior.counts_by_score[24][(3, 3, 0, 1, 0)] == 1
    assert prior.counts_by_score[17][(2, 2, 0, 1, 0)] == 1


def test_rejects_unlabeled_or_fractional_training_rows():
    with pytest.raises(ScoreCountScoringPriorBridgeError):
        score_count_training_rows_to_composition_rows([_row(made_field_goals=None)])
    with pytest.raises(ScoreCountScoringPriorBridgeError):
        score_count_training_rows_to_composition_rows([_row(pat_made=2.5)])


def test_conservative_completion_receipt_still_enforces_cutoff():
    with pytest.raises(ValueError, match="PIT_FUTURE_OR_SAME_TIME_ROW"):
        fit_scoring_prior_from_score_count_training_rows(
            [_row()],
            as_of="2025-09-08T12:00:00+00:00",
        )
