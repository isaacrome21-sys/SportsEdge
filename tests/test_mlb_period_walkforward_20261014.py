"""Synthetic chronological evaluation tests; no historical results fabricated."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_period_walkforward import evaluate_period_walkforward


def _games(n=30):
    return [
        {"game_id": f"g{i}", "start_time": (datetime(2026, 8, 1, 18, tzinfo=timezone.utc) + timedelta(days=i)).isoformat(),
         "inning_runs": [i % 3, 0, 1, 0, 0, 0, 0, 0, 0]}
        for i in range(n)
    ]


@pytest.mark.parametrize("innings", [3, 7])
def test_forward_scores_are_bounded_and_research_only(innings):
    report = evaluate_period_walkforward(_games(), innings=innings, min_train=20)
    assert report["forward_predictions"] == 10
    assert 0 <= report["empirical_brier"] <= 1
    assert 0 <= report["poisson_baseline_brier"] <= 1
    assert not report["validated"]
    assert not report["play_authorized"]


def test_duplicate_ids_refused():
    games = _games()
    games[-1]["game_id"] = games[0]["game_id"]
    with pytest.raises(ValueError, match="DUPLICATE"):
        evaluate_period_walkforward(games, innings=3)


def test_same_time_games_do_not_train_on_each_other():
    games = _games(21)
    games[-1]["start_time"] = games[-2]["start_time"]
    with pytest.raises(ValueError, match="NO_FORWARD_EVALUATION_ROWS"):
        evaluate_period_walkforward(games, innings=3, min_train=20)


def test_invalid_line_refused():
    with pytest.raises(ValueError, match="HALF_INTEGER"):
        evaluate_period_walkforward(_games(), innings=3, half_line=2)


def test_no_forward_rows_refused():
    with pytest.raises(ValueError, match="NO_FORWARD_EVALUATION_ROWS"):
        evaluate_period_walkforward(_games(20), innings=3, min_train=20)
