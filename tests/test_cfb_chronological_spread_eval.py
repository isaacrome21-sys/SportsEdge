from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.cfb.candidate_registry_v2 import EQUAL
from sportsedge.sports.cfb.chronological_spread_eval import (
    CFBChronologicalSpreadEvalError,
    evaluate_candidate_spread_chronologically,
)


_KEYS = (
    "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
    "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
    "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
    "net_field_position", "explosive_rate",
)


def _metrics(x):
    return {k: float(x + i / 100.0) for i, k in enumerate(_KEYS)}


def _row(i):
    dt = datetime(2024, 8, 1, tzinfo=timezone.utc) + timedelta(days=i)
    return {
        "kickoff_utc": dt.isoformat().replace("+00:00", "Z"), "season": 2024,
        "home_score": 24 + (i % 10), "away_score": 17 + (i % 7), "neutral_site": False,
        "weather": {"game_indoor": True},
        "home_metrics": _metrics(1.0 + i / 100.0), "away_metrics": _metrics(.8 + i / 120.0),
    }


def test_chronological_spread_eval_uses_past_to_predict_future():
    rows = [_row(i) for i in range(45)]
    result = evaluate_candidate_spread_chronologically(
        rows, family=EQUAL, ridge_alpha=10.0,
        cutoffs_utc=[rows[25]["kickoff_utc"], rows[35]["kickoff_utc"]],
    )
    assert result.n_predictions == 20
    assert result.folds[0].n_train == 25
    assert result.folds[0].n_test == 10
    assert result.folds[1].n_train == 35
    assert result.folds[1].n_test == 10
    assert result.pooled_margin_rmse >= 0


def test_naive_kickoff_is_rejected():
    rows = [_row(i) for i in range(25)]
    rows[0]["kickoff_utc"] = "2024-08-01T12:00:00"
    with pytest.raises(CFBChronologicalSpreadEvalError, match="OFFSET_REQUIRED"):
        evaluate_candidate_spread_chronologically(
            rows, family=EQUAL, ridge_alpha=10.0, cutoffs_utc=[rows[20]["kickoff_utc"]]
        )


def test_unsorted_or_duplicate_cutoffs_fail_closed():
    rows = [_row(i) for i in range(30)]
    with pytest.raises(CFBChronologicalSpreadEvalError, match="STRICTLY_INCREASING"):
        evaluate_candidate_spread_chronologically(
            rows, family=EQUAL, ridge_alpha=10.0,
            cutoffs_utc=[rows[25]["kickoff_utc"], rows[20]["kickoff_utc"]],
        )
