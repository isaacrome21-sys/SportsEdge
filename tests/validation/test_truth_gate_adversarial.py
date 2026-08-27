from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path

import pytest

from sportsedge.sports.cfb.truth_gate import CFBTruthGate
from sportsedge.sports.mlb.truth_gate import MLBTruthGate
from sportsedge.sports.nfl.truth_gate import NFLTruthGate
from sportsedge.validation.truth_gate_core import (
    CandidateDecision,
    MarketStatus,
    TruthGateCore,
    TruthGatePolicyError,
)

ROOT = Path(__file__).resolve().parents[2]


def base_passing(gate, market: str, **overrides):
    data = dict(
        evidence_market=market,
        evidence_policy_sha256=gate.policy_sha256,
        pit_reproducible=True,
        leakage_violations=0,
        n_forward_seasons=5,
        brier_model=0.20,
        brier_market=0.22,
        logloss_model=0.55,
        logloss_market=0.58,
        season_fold_scoring_win_rate=0.75,
        mean_novig_clv=0.006,
        clv_t_stat=2.5,
        roi_after_vig=0.025,
        calibration_slope=1.00,
        calibration_intercept=0.01,
        ece=0.015,
        n_promoted=250,
        recent_two_season_ok=True,
        coherent_joint=True,
        shared_path_ok=True,
        paired_historical_price_evidence_complete=True,
        model_prob=0.56,
        no_vig_prob=0.50,
        live_two_sided_quote=True,
        data_fresh=True,
        exposure_limits_ok=True,
    )
    data.update(overrides)
    return data


@pytest.fixture(params=["MLB", "NFL", "CFB"])
def gate_and_market(request):
    if request.param == "MLB":
        return MLBTruthGate(ROOT / "config" / "mlb_truth_gate_v1.json"), "V7_GAME"
    if request.param == "NFL":
        return NFLTruthGate(ROOT / "config" / "nfl_truth_gate_v1.json"), "GAME"
    return CFBTruthGate(ROOT / "config" / "cfb_truth_gate_v1.json"), "MONEYLINE"


def evaluate(gate, market, **overrides):
    payload = base_passing(gate, market, **overrides)
    if isinstance(gate, MLBTruthGate):
        return gate.evaluate_family(market, **payload)
    if isinstance(gate, NFLTruthGate):
        return gate.evaluate_surface(market, **payload)
    return gate.evaluate(market, **payload)


def test_fully_passing_historical_market_is_official(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market)
    assert report.hard_gate_pass is True
    assert report.market_status == MarketStatus.OFFICIAL
    assert report.candidate_decision == CandidateDecision.OFFICIAL_BET


def test_live_edge_cannot_change_market_status(gate_and_market):
    gate, market = gate_and_market
    high = evaluate(gate, market, model_prob=0.56, no_vig_prob=0.50)
    low = evaluate(gate, market, model_prob=0.51, no_vig_prob=0.50)
    assert high.market_status == low.market_status == MarketStatus.OFFICIAL
    assert high.candidate_decision == CandidateDecision.OFFICIAL_BET
    assert low.candidate_decision == CandidateDecision.NO_BET


def test_stale_quote_keeps_market_official_but_blocks_candidate(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, live_two_sided_quote=False, data_fresh=False)
    assert report.hard_gate_pass is True
    assert report.market_status == MarketStatus.OFFICIAL
    assert report.candidate_decision == CandidateDecision.BLOCKED
    assert "LIVE_TWO_SIDED_QUOTE_MISSING" in report.candidate_failures
    assert "DATA_NOT_FRESH" in report.candidate_failures


def test_exposure_violation_blocks_candidate_only(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, exposure_limits_ok=False)
    assert report.hard_gate_pass is True
    assert report.market_status == MarketStatus.OFFICIAL
    assert report.candidate_decision == CandidateDecision.BLOCKED
    assert "EXPOSURE_LIMITS_VIOLATED" in report.candidate_failures


@pytest.mark.parametrize("bad", [None, "abc", True, float("nan"), float("inf")])
def test_none_or_malformed_metric_fails_structured(gate_and_market, bad):
    gate, market = gate_and_market
    report = evaluate(gate, market, brier_model=bad)
    assert report.hard_gate_pass is False
    assert report.market_status == MarketStatus.EVIDENCE_INCOMPLETE
    assert report.candidate_decision == CandidateDecision.BLOCKED
    assert any("NUMERIC_REQUIRED" in x or "FINITE_REQUIRED" in x for x in report.market_failures)


@pytest.mark.parametrize(
    "field",
    ["n_promoted", "n_forward_seasons", "leakage_violations"],
)
def test_negative_counts_rejected(gate_and_market, field):
    gate, market = gate_and_market
    report = evaluate(gate, market, **{field: -1})
    assert report.hard_gate_pass is False
    assert any("NONNEGATIVE_INTEGER_REQUIRED" in x for x in report.market_failures)


@pytest.mark.parametrize(
    "field",
    ["n_promoted", "n_forward_seasons", "leakage_violations"],
)
def test_fractional_counts_rejected(gate_and_market, field):
    gate, market = gate_and_market
    report = evaluate(gate, market, **{field: 3.5})
    assert report.hard_gate_pass is False
    assert any("NONNEGATIVE_INTEGER_REQUIRED" in x for x in report.market_failures)


def test_one_leakage_violation_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, leakage_violations=1)
    assert report.hard_gate_pass is False
    assert report.market_status != MarketStatus.OFFICIAL
    assert report.candidate_decision == CandidateDecision.BLOCKED
    assert "LEAKAGE_VIOLATIONS_EXCEEDED" in report.market_failures


def test_199_promoted_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, n_promoted=199)
    assert report.hard_gate_pass is False
    assert report.market_status == MarketStatus.EVIDENCE_INCOMPLETE
    assert "PROMOTED_SAMPLE_BELOW_ABSOLUTE_FLOOR" in report.market_failures


def test_brier_pass_logloss_fail_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(
        gate,
        market,
        brier_model=0.20,
        brier_market=0.22,
        logloss_model=0.60,
        logloss_market=0.55,
    )
    assert report.hard_gate_pass is False
    assert "LOGLOSS_DOES_NOT_BEAT_MARKET" in report.market_failures


def test_clv_t_stat_1_99_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, clv_t_stat=1.99)
    assert report.hard_gate_pass is False
    assert "CLV_T_STAT_BELOW_FLOOR" in report.market_failures


def test_roi_exactly_zero_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, roi_after_vig=0.0)
    assert report.hard_gate_pass is False
    assert "ROI_AFTER_VIG_NOT_POSITIVE" in report.market_failures


@pytest.mark.parametrize("slope", [0.899, 1.101])
def test_calibration_slope_out_of_range_blocks(gate_and_market, slope):
    gate, market = gate_and_market
    report = evaluate(gate, market, calibration_slope=slope)
    assert report.hard_gate_pass is False
    assert "CALIBRATION_SLOPE_OUT_OF_RANGE" in report.market_failures


def test_ece_above_max_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, ece=0.0251)
    assert report.hard_gate_pass is False
    assert "ECE_ABOVE_MAX" in report.market_failures


def test_recent_two_season_degradation_blocks(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, recent_two_season_ok=False)
    assert report.hard_gate_pass is False
    assert "RECENT_TWO_SEASON_DETERIORATION" in report.market_failures


def test_policy_sha_mismatch_blocks_market(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, evidence_policy_sha256="deadbeef" * 8)
    assert report.hard_gate_pass is False
    assert report.market_status == MarketStatus.EVIDENCE_INCOMPLETE
    assert "POLICY_SHA256_MISMATCH" in report.market_failures


def test_evidence_market_identity_cannot_be_relabelled(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, evidence_market="SOMETHING_ELSE")
    assert report.hard_gate_pass is False
    assert "EVIDENCE_MARKET_IDENTITY_MISMATCH" in report.market_failures


def test_invalid_market_family_surface_blocks(gate_and_market):
    gate, _ = gate_and_market
    bad = "NOT_A_REAL_SURFACE"
    payload = base_passing(gate, bad)
    if isinstance(gate, MLBTruthGate):
        report = gate.evaluate_family(bad, **payload)
    elif isinstance(gate, NFLTruthGate):
        report = gate.evaluate_surface(bad, **payload)
    else:
        report = gate.evaluate(bad, **payload)
    assert report.hard_gate_pass is False
    assert "INVALID_MARKET_OR_FAMILY" in report.market_failures


def test_missing_coherence_defaults_to_fail_mlb():
    gate = MLBTruthGate(ROOT / "config" / "mlb_truth_gate_v1.json")
    payload = base_passing(gate, "HITTER_JOINT")
    payload.pop("coherent_joint")
    report = gate.evaluate_family("HITTER_JOINT", **payload)
    assert report.hard_gate_pass is False
    assert "JOINT_COHERENCE_FAILED" in report.market_failures


def test_missing_shared_path_defaults_to_fail_nfl():
    gate = NFLTruthGate(ROOT / "config" / "nfl_truth_gate_v1.json")
    payload = base_passing(gate, "GAME")
    payload.pop("shared_path_ok")
    report = gate.evaluate_surface("GAME", **payload)
    assert report.hard_gate_pass is False
    assert "SHARED_PATH_COHERENCE_FAILED" in report.market_failures


def test_missing_paired_historical_prices_blocks_cfb():
    gate = CFBTruthGate(ROOT / "config" / "cfb_truth_gate_v1.json")
    report = evaluate(
        gate,
        "MONEYLINE",
        paired_historical_price_evidence_complete=False,
    )
    assert report.hard_gate_pass is False
    assert "PAIRED_HISTORICAL_PRICE_EVIDENCE_REQUIRED" in report.market_failures


@pytest.mark.parametrize(
    ("model_prob", "no_vig_prob"),
    [
        (None, 0.5),
        ("bad", 0.5),
        (float("nan"), 0.5),
        (1.1, 0.5),
        (-0.1, 0.5),
        (0.55, 1.2),
    ],
)
def test_invalid_live_probabilities_block_candidate_not_market(
    gate_and_market,
    model_prob,
    no_vig_prob,
):
    gate, market = gate_and_market
    report = evaluate(
        gate,
        market,
        model_prob=model_prob,
        no_vig_prob=no_vig_prob,
    )
    assert report.hard_gate_pass is True
    assert report.market_status == MarketStatus.OFFICIAL
    assert report.candidate_decision == CandidateDecision.BLOCKED
    assert report.candidate_failures


def test_sport_specific_failure_blocks_market(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(
        gate,
        market,
        sport_specific_failures={True: "EXTERNAL_ATTESTATION_REQUIRED"},
    )
    assert report.hard_gate_pass is False
    assert "EXTERNAL_ATTESTATION_REQUIRED" in report.market_failures


def test_deterministic_identical_report_hash(gate_and_market):
    gate, market = gate_and_market
    r1 = evaluate(gate, market)
    r2 = evaluate(gate, market)
    assert r1.content_hash() == r2.content_hash()


def test_changed_evidence_new_hash(gate_and_market):
    gate, market = gate_and_market
    r1 = evaluate(gate, market)
    r2 = evaluate(gate, market, mean_novig_clv=0.007)
    assert r1.content_hash() != r2.content_hash()


def test_gate_report_is_frozen(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market)
    with pytest.raises(FrozenInstanceError):
        report.market_status = MarketStatus.REVOKED


def test_no_review_override_path_exists(gate_and_market):
    gate, market = gate_and_market
    report = evaluate(gate, market, leakage_violations=1, review=True, force=True)
    assert report.market_status != MarketStatus.OFFICIAL
    assert report.candidate_decision != CandidateDecision.OFFICIAL_BET


def test_missing_policy_threshold_rejected_at_load(tmp_path):
    bad_policy = {
        "policy_id": "BAD",
        "version": "1.0.0",
        "hard_gates": {"edge_floor": 0.03},
        "markets": ["GAME"],
    }
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(bad_policy), encoding="utf-8")
    with pytest.raises(TruthGatePolicyError, match="POLICY_FIELDS_MISSING"):
        TruthGateCore(path)
