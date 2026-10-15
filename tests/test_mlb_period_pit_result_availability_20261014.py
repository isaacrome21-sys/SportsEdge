"""Point-in-time result-availability refusal regressions."""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_period_walkforward import evaluate_period_walkforward


def _rows():
    base = datetime(2024, 4, 1, tzinfo=timezone.utc)
    return [
        {"game_id": str(i), "start_time": (base + timedelta(days=i)).isoformat(),
         "result_available_at": (base + timedelta(days=i, hours=4)).isoformat(),
         "inning_runs": [int(i % 2 == 0)] + [0] * 8}
        for i in range(23)
    ]


def test_missing_availability_refused():
    rows = _rows()
    del rows[0]["result_available_at"]
    with pytest.raises(ValueError, match="MISSING_RESULT_AVAILABILITY"):
        evaluate_period_walkforward(rows, innings=3)


def test_impossible_availability_refused():
    rows = _rows()
    rows[0]["result_available_at"] = rows[0]["start_time"]
    with pytest.raises(ValueError, match="RESULT_AVAILABLE_BEFORE_START"):
        evaluate_period_walkforward(rows, innings=3)


def test_prior_start_but_late_result_excluded():
    rows = _rows()
    rows[0]["result_available_at"] = (
        datetime(2024, 5, 1, tzinfo=timezone.utc).isoformat())
    report = evaluate_period_walkforward(rows, innings=3, min_train=20)
    assert report["forward_predictions"] == 2
    assert report["play_authorized"] is False
