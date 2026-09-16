from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from sportsedge.mlb_moneyline_forward_prediction import (
    MLBMoneylineForwardPredictionBlocked,
    MLBMoneylineForwardPredictionError,
    build_forward_prediction,
    capture_due_predictions,
)


class FakeHistory:
    def __init__(self, retrieved_at, n=12):
        self.retrieved_at = retrieved_at
        self.n = n

    def team_rows(self, *, team_id, target_date):
        base = 3 if int(team_id) == 10 else 4
        rows = []
        for i in range(self.n):
            rows.append({
                "date": target_date - timedelta(days=self.n - i),
                "stat": {"runs": base + (i % 3)},
            })
        return rows


def snapshot(start, game_pk=123):
    return SimpleNamespace(
        game_pk=game_pk,
        game_date=start.isoformat(),
        status="Preview",
        away_id=10,
        away_name="Away Club",
        home_id=20,
        home_name="Home Club",
        official_date=start.date().isoformat(),
    )


def test_build_prediction_is_market_blind_fixed_home_reference():
    now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
    start = now + timedelta(minutes=50)
    out = build_forward_prediction(
        snapshot=snapshot(start),
        history=FakeHistory(now),
        now=now,
        artifact_sha="a" * 64,
        simulations=2000,
    )
    assert out["market"] == "MONEYLINE"
    assert out["market_blind"] is True
    assert out["model_side"] == "HOME"
    assert out["reference_side_policy"] == "FIXED_HOME_REFERENCE_NO_MARKET_SELECTION"
    assert 0 < out["model_p"] < 1
    assert datetime.fromisoformat(out["feature_asof_ts"]) < start
    assert out["promotion_authority"] is False
    assert "odds" in out["forbidden_market_inputs"]
    assert out["feature_observation_count"] == 24
    assert len(out["feature_observations"]) == 24


def test_prediction_after_start_fails_closed():
    now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
    with pytest.raises(MLBMoneylineForwardPredictionError, match="precede"):
        build_forward_prediction(
            snapshot=snapshot(now),
            history=FakeHistory(now),
            now=now,
            artifact_sha="a" * 64,
            simulations=2000,
        )


def test_insufficient_history_blocks_due_game(tmp_path):
    now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
    start = now + timedelta(minutes=50)
    with pytest.raises(MLBMoneylineForwardPredictionBlocked, match="BLOCKED_DUE_MODEL_P"):
        capture_due_predictions(
            schedule=[snapshot(start)],
            history=FakeHistory(now, n=9),
            now=now,
            output_dir=tmp_path,
            artifact_sha="a" * 64,
            simulations=2000,
        )


def test_capture_is_create_only_and_only_inside_window(tmp_path):
    now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
    due = snapshot(now + timedelta(minutes=50), 123)
    later = snapshot(now + timedelta(minutes=90), 456)
    first = capture_due_predictions(
        schedule=[due, later],
        history=FakeHistory(now),
        now=now,
        output_dir=tmp_path,
        artifact_sha="a" * 64,
        simulations=2000,
    )
    assert first["status"] == "RETAINED"
    assert first["games_due"] == 1
    assert first["predictions_retained"] == 1
    path = Path(first["paths"][0])
    before = path.read_bytes()

    second = capture_due_predictions(
        schedule=[due, later],
        history=FakeHistory(now),
        now=now,
        output_dir=tmp_path,
        artifact_sha="a" * 64,
        simulations=2000,
    )
    assert second["status"] == "ALREADY_CAPTURED"
    assert path.read_bytes() == before


def test_no_due_game_is_green_but_non_authoritative(tmp_path):
    now = datetime(2026, 9, 20, 18, 10, tzinfo=timezone.utc)
    out = capture_due_predictions(
        schedule=[snapshot(now + timedelta(minutes=90))],
        history=FakeHistory(now),
        now=now,
        output_dir=tmp_path,
        artifact_sha="a" * 64,
        simulations=2000,
    )
    assert out["status"] == "NO_PREDICTION_DUE"
    assert out["promotion_authority"] is False
