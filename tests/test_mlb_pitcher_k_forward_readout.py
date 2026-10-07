from copy import deepcopy

import pytest

from sportsedge.mlb_pitcher_k_forward_readout import (
    MIN_GRADED_UNITS,
    PitcherKForwardReadoutError,
    build_readout,
    select_judged_units,
)
from sportsedge.mlb_pitcher_k_forward_validation import canonical_sha256


def _prediction(game_pk, pitcher_id, hour, *, p=0.60, q=0.50):
    row = {
        "schema": "SPORTSEDGE_MLB_PITCHER_K_FORWARD_PREDICTION_V1",
        "status": "CAPTURED_PROSPECTIVE",
        "market": "PITCHER_K",
        "game_pk": game_pk,
        "pitcher_id": pitcher_id,
        "pitcher_team_id": 1,
        "entity_name": f"P{pitcher_id}",
        "provider_event_id": f"e{game_pk}",
        "line": 5.5,
        "over_odds": -110,
        "under_odds": -110,
        "market_fair_p_over": q,
        "candidate_p_over": p,
        "candidate_p_under": 1-p,
        "candidate_p_push": 0.0,
        "projected_batters_faced": 24,
        "predicted_k_per_batter_faced": 0.25,
        "observed_at_utc": f"2026-10-07T{hour:02d}:00:00+00:00",
        "first_pitch_at_utc": "2026-10-07T23:00:00+00:00",
        "fit_sha256": "70a31ff9b995a2d54df87feb2d51e2518fa9cd8593bf6c047970e08557b6ecea",
        "evaluation_run_id": 37603403636,
        "quote_archive_path": "runtime/mlb-prop-pit/x.json",
        "context_proof": {"path": "c"},
        "statcast_proof": {"path": "s"},
        "authority": {
            "forward_validation_evidence_only": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
    }
    row["receipt_sha256"] = canonical_sha256(row)
    return row


def _settlement(prediction, *, win=True, diff=-0.10, cb=0.16, mb=0.25):
    row = {
        "schema": "SPORTSEDGE_MLB_PITCHER_K_FORWARD_SETTLEMENT_V1",
        "prediction_sha256": prediction["receipt_sha256"],
        "game_pk": prediction["game_pk"],
        "pitcher_id": prediction["pitcher_id"],
        "line": prediction["line"],
        "settled_at_utc": "2026-10-08T03:00:00+00:00",
        "authority": {
            "forward_validation_evidence_only": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
        "status": "GRADED",
        "realized_strikeouts": 7 if win else 4,
        "outcome_over": win,
        "candidate_log_loss": 0.40,
        "market_log_loss": 0.50,
        "candidate_minus_market_log_loss": diff,
        "candidate_brier": cb,
        "market_brier": mb,
    }
    row["receipt_sha256"] = canonical_sha256(row)
    return row


def test_selection_uses_last_prediction_per_game_pitcher():
    early = _prediction(1, 10, 18)
    late = _prediction(1, 10, 20)
    settlements = [_settlement(early), _settlement(late)]
    judged = select_judged_units([early, late], settlements)
    assert len(judged) == 1
    assert judged[0]["prediction_sha256"] == late["receipt_sha256"]


def test_void_last_prediction_is_not_graded():
    pred = _prediction(1, 10, 20)
    void = {
        "schema": "SPORTSEDGE_MLB_PITCHER_K_FORWARD_SETTLEMENT_V1",
        "prediction_sha256": pred["receipt_sha256"],
        "game_pk": 1,
        "pitcher_id": 10,
        "line": 5.5,
        "settled_at_utc": "2026-10-08T03:00:00+00:00",
        "authority": {
            "forward_validation_evidence_only": True,
            "production_activation": False,
            "promotion": False,
            "official": False,
        },
        "status": "VOID_NOT_STARTER",
        "realized_strikeouts": None,
    }
    void["receipt_sha256"] = canonical_sha256(void)
    assert select_judged_units([pred], [void]) == []


def test_readout_fails_closed_below_minimum():
    pred = _prediction(1, 10, 20)
    with pytest.raises(PitcherKForwardReadoutError, match="INSUFFICIENT_GRADED_UNITS"):
        build_readout([pred], [_settlement(pred)])


def test_readout_passes_when_frozen_rules_all_hold():
    predictions = []
    settlements = []
    for i in range(MIN_GRADED_UNITS):
        pred = _prediction(i + 1, 1000 + (i % 30), 20)
        predictions.append(pred)
        settlements.append(_settlement(pred, diff=-0.10, cb=0.16, mb=0.25))
    result = build_readout(predictions, settlements)
    assert result["graded_units"] == MIN_GRADED_UNITS
    assert result["candidate_minus_market_log_loss_ci"]["hi"] < 0
    assert result["passes_forward_validation_gate"] is True
    assert result["authority"]["production_activation"] is False


def test_readout_failure_does_not_activate_production():
    predictions = []
    settlements = []
    for i in range(MIN_GRADED_UNITS):
        pred = _prediction(i + 1, 2000 + (i % 30), 20)
        predictions.append(pred)
        settlements.append(_settlement(pred, diff=0.10, cb=0.30, mb=0.25))
    result = build_readout(predictions, settlements)
    assert result["passes_forward_validation_gate"] is False
    assert set(result["blockers"]) == {
        "LOG_LOSS_CI_NOT_ENTIRELY_BELOW_ZERO",
        "CANDIDATE_BRIER_WORSE_THAN_MARKET",
    }
    assert result["authority"]["production_activation"] is False
