from copy import deepcopy

import pytest

from sportsedge.mlb_pitcher_k_forward_validation import (
    PitcherKForwardValidationError,
    build_prediction_receipt,
    load_frozen_fit,
    settle_prediction,
)


def _candidate():
    return {
        "schema": "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1",
        "authority": "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED",
        "source_complete": True,
        "missing_components": [],
        "deployment": False,
        "model_p_eligible": False,
        "components": {
            "workload_leash": {
                "summary": {
                    "recent_mean_batters_faced": 24.0,
                    "recent_mean_k_per_batter_faced": 0.26,
                    "recent_mean_pitches_per_batter_faced": 4.0,
                }
            },
            "opponent_k": {"target_rel": 1.05},
            "lineup_k": None,
            "pitcher_skill": {
                "whiff_rate": 0.30,
                "chase_rate": 0.31,
                "pitcher_hand": "R",
            },
        },
    }


def _receipt():
    return build_prediction_receipt(
        candidate=_candidate(),
        game_pk=123,
        pitcher_id=456,
        pitcher_team_id=10,
        line=5.5,
        over_odds=-110,
        under_odds=-110,
        observed_at="2026-10-07T22:00:00+00:00",
        first_pitch_at="2026-10-07T23:00:00+00:00",
        provider_event_id="dk-1",
        entity_name="Example Pitcher",
        quote_archive_path="runtime/mlb-prop-pit/2026-10-07/props_x.json",
        context_proof={"path": "runtime/mlb-context/runs/1/2026-10-07/game_123.json"},
        statcast_proof={"manifest_path": "runtime/statcast/runs/2/2026-10-07/manifest.json"},
    )


def test_frozen_fit_identity_is_exact_and_development_only():
    fit, concentration, payload = load_frozen_fit()
    assert fit.fit_sha256 == "70a31ff9b995a2d54df87feb2d51e2518fa9cd8593bf6c047970e08557b6ecea"
    assert fit.ridge_alpha == 100.0
    assert concentration == 100.0
    assert payload["authority"]["production_activation"] is False


def test_prediction_receipt_uses_frozen_fit_and_paired_market():
    receipt = _receipt()
    assert receipt["status"] == "CAPTURED_PROSPECTIVE"
    assert receipt["fit_sha256"] == "70a31ff9b995a2d54df87feb2d51e2518fa9cd8593bf6c047970e08557b6ecea"
    assert receipt["market_fair_p_over"] == pytest.approx(0.5)
    assert 0.0 < receipt["candidate_p_over"] < 1.0
    assert receipt["authority"]["production_activation"] is False
    assert len(receipt["receipt_sha256"]) == 64


def test_prediction_fails_closed_at_or_after_first_pitch():
    with pytest.raises(PitcherKForwardValidationError, match="not pregame"):
        build_prediction_receipt(
            candidate=_candidate(),
            game_pk=123,
            pitcher_id=456,
            pitcher_team_id=10,
            line=5.5,
            over_odds=-110,
            under_odds=-110,
            observed_at="2026-10-07T23:00:00+00:00",
            first_pitch_at="2026-10-07T23:00:00+00:00",
            provider_event_id="dk-1",
            entity_name="Example Pitcher",
            quote_archive_path="q.json",
            context_proof={},
            statcast_proof={},
        )


def test_settlement_is_bound_to_saved_prediction_not_recomputed():
    prediction = _receipt()
    original = deepcopy(prediction)
    settled = settle_prediction(
        prediction,
        realized_strikeouts=7,
        started=True,
        settled_at="2026-10-08T03:00:00+00:00",
    )
    assert prediction == original
    assert settled["status"] == "GRADED"
    assert settled["prediction_sha256"] == prediction["receipt_sha256"]
    assert settled["realized_strikeouts"] == 7
    assert settled["outcome_over"] is True
    assert "candidate_minus_market_log_loss" in settled


def test_nonstarter_is_void_and_not_graded():
    prediction = _receipt()
    settled = settle_prediction(
        prediction,
        realized_strikeouts=None,
        started=False,
        settled_at="2026-10-08T03:00:00+00:00",
    )
    assert settled["status"] == "VOID_NOT_STARTER"
    assert settled["realized_strikeouts"] is None
    assert "candidate_log_loss" not in settled
