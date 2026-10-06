import pytest

from sportsedge.mlb_pitcher_k_evaluation_runner import (
    PitcherKEvaluationRunnerError,
    _validate_rows,
)


def _row(season, game_id, pitcher_id="501"):
    return {
        "schema": "MLB_PITCHER_K_HISTORICAL_EVALUATION_ROW_V1",
        "season": season,
        "target_date": f"{season}-06-01",
        "game_id": game_id,
        "pitcher_id": pitcher_id,
        "historical_reconstruction": True,
        "backfill": True,
        "forward_evidence_eligible": False,
        "promotion_authority": False,
    }


def _split():
    return [_row(2023, 1), _row(2024, 2), _row(2025, 3)]


def test_runner_accepts_only_complete_frozen_split():
    got = _validate_rows(_split())
    assert [row["season"] for row in got] == [2023, 2024, 2025]


def test_runner_rejects_forward_evidence_claim():
    rows = _split()
    rows[-1]["forward_evidence_eligible"] = True
    with pytest.raises(PitcherKEvaluationRunnerError, match="cannot grant"):
        _validate_rows(rows)


def test_runner_rejects_missing_frozen_season():
    with pytest.raises(PitcherKEvaluationRunnerError, match="all frozen split seasons"):
        _validate_rows(_split()[:2])


def test_runner_rejects_duplicate_pitcher_start():
    rows = _split()
    rows.append(dict(rows[-1]))
    with pytest.raises(PitcherKEvaluationRunnerError, match="duplicate"):
        _validate_rows(rows)


def test_runner_rejects_target_date_season_mismatch():
    rows = _split()
    rows[1]["target_date"] = "2025-06-01"
    with pytest.raises(PitcherKEvaluationRunnerError, match="target date/season mismatch"):
        _validate_rows(rows)
