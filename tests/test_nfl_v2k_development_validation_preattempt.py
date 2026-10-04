from __future__ import annotations

import json
from pathlib import Path

from sportsedge.sports.nfl import v2k_drive_core, v2k_drive_source

ROOT = Path(__file__).resolve().parents[1]
NFL = ROOT / "sportsedge" / "sports" / "nfl"
CONTRACT = NFL / "NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V1.json"
SOURCE_FREEZE = ROOT / "config" / "nfl_promotion_source_freeze_v1.json"
REFERENCE = NFL / "NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1.json"
LEDGER = NFL / "NFL_V2K_ATTEMPT_LEDGER_V1.json"
ADMISSION = NFL / "NFL_V2K_IMPLEMENTATION_ADMISSION_V3.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_preattempt_contract_stays_blocked_and_consumes_no_attempt() -> None:
    c = _load(CONTRACT)
    ledger = _load(LEDGER)
    admission = _load(ADMISSION)
    assert c["status"] == "BLOCKED_PRE_ATTEMPT_FREEZE_INCOMPLETE"
    assert c["candidate_family"] == admission["candidate_family"]
    assert ledger["attempts_used"] == 0
    assert ledger["attempts"] == []
    assert c["attempt_budget"]["attempts_used"] == 0
    assert c["attempt_budget"]["this_artifact_consumes_attempt"] is False
    assert c["attempt_budget"]["attempt_1_scoring_allowed"] is False
    assert c["attempt_budget"]["untouched_readout_allowed"] is False


def test_source_binding_uses_existing_immutable_2018_2025_pbp_freeze() -> None:
    c = _load(CONTRACT)
    source = _load(SOURCE_FREEZE)
    assert source["contract"] == c["source_binding"]["source_freeze_contract"]
    assert source["frozen_from_evidence"]["source_manifest_sha256"] == c["source_binding"]["source_manifest_sha256"]
    pbp = source["seasonal_sources"]["pbp"]
    expected = list(range(2018, 2026))
    assert c["source_binding"]["pbp_seasons"] == expected
    assert all(season in pbp["seasons"] for season in expected)
    assert {str(s): pbp["expected_sha256_by_season"][str(s)] for s in expected} == c["source_binding"]["pbp_sha256_by_season"]


def test_feature_contract_matches_market_blind_drive_adapter() -> None:
    c = _load(CONTRACT)["feature_contract"]
    assert set(c["required_input_fields"]) == set(v2k_drive_source._REQUIRED)
    assert set(c["forbidden_market_fields"]) == set(v2k_drive_source._FORBIDDEN_MARKET_KEYS)
    assert tuple(c["drive_outcomes"]) == v2k_drive_core.DRIVE_OUTCOMES
    assert c["overtime_rule_version"] == v2k_drive_core.OVERTIME_RULE_VERSION
    assert c["truncation_policy_version"] == v2k_drive_core.TRUNCATION_POLICY_VERSION


def test_structural_thresholds_are_copied_from_frozen_empirical_reference() -> None:
    c = _load(CONTRACT)["already_frozen_gates"]
    reference = _load(REFERENCE)
    control = reference["frozen_control"]
    gate = reference["structural_improvement_gate"]
    assert c["signed_keys"] == reference["required_signed_keys"]
    assert c["absolute_signed_key_mass_error_max"] == reference["absolute_mass_tolerance"]
    assert c["control_calibration_slope"] == control["calibration_slope"]
    assert c["control_calibration_slope_metric"] == control["calibration_slope_metric"]
    assert c["control_signed_key_mass_rmse"] == control["signed_key_mass_rmse"]
    assert c["candidate_calibration_slope_metric_must_be_strictly_less_than_control"] is gate["candidate_must_strictly_improve_calibration_slope_metric"]
    assert c["candidate_signed_key_mass_rmse_must_be_strictly_less_than_control"] is gate["candidate_must_strictly_improve_signed_key_mass_metric"]
    assert c["both_structural_improvements_required"] is (not gate["either_dimension_alone_counts_as_pass"])


def test_unresolved_freezes_are_explicit_and_authority_remains_zero() -> None:
    c = _load(CONTRACT)
    unresolved = c["unresolved_required_freezes"]
    assert set(unresolved) == {
        "chronological_fold_plan",
        "rng_algorithm_version_and_seed_policy",
        "simulation_count",
        "predictive_acceptance_thresholds",
    }
    assert all(value is None for value in unresolved.values())
    assert len(c["blocker_codes"]) == 4
    for key, value in c["authority"].items():
        if key == "research_contract":
            assert value is True
        else:
            assert value is False
