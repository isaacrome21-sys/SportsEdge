from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.mlb_moneyline_evidence import (
    MLBMoneylineEvidenceError,
    evaluate_moneyline_predictions,
)


def _rows(n=200):
    start = datetime(2026, 4, 1, 23, tzinfo=timezone.utc)
    rows = []
    # Deliberately varied probabilities/outcomes; tests contract, not promotion.
    for i in range(n):
        p = 0.35 + (i % 30) / 100.0
        y = 1 if (i * 17) % 100 < int(p * 100) else 0
        rows.append({
            "model_p": p,
            "outcome": y,
            "market_blind": True,
            "feature_asof_ts": (start - timedelta(hours=1)).isoformat(),
            "event_start_ts": start.isoformat(),
        })
    return rows


def test_empty_is_blocked_not_promoted():
    out = evaluate_moneyline_predictions([])
    assert out["status"] == "BLOCKED_NO_PREDICTIONS"
    assert out["promotion_authority"] is False


def test_metrics_emitted_and_clv_stays_separate():
    out = evaluate_moneyline_predictions(_rows())
    for key in ("brier", "log_loss", "calibration_slope", "calibration_intercept", "ece"):
        assert key in out
    assert out["n"] == 200
    assert out["sample_gate_pass"] is True
    assert out["clv_status"] == "SEPARATE_EVIDENCE_REQUIRED"
    assert out["promotion_authority"] is False


def test_under_200_cannot_clear_sample_gate():
    out = evaluate_moneyline_predictions(_rows(199))
    assert out["sample_gate_pass"] is False
    assert out["promotion_authority"] is False


def test_market_blindness_is_hard_requirement():
    rows = _rows()
    rows[0]["market_blind"] = False
    with pytest.raises(MLBMoneylineEvidenceError, match="market_blind"):
        evaluate_moneyline_predictions(rows)


def test_equal_asof_and_start_is_leakage():
    rows = _rows()
    rows[0]["feature_asof_ts"] = rows[0]["event_start_ts"]
    with pytest.raises(MLBMoneylineEvidenceError, match="PIT_LEAKAGE"):
        evaluate_moneyline_predictions(rows)
