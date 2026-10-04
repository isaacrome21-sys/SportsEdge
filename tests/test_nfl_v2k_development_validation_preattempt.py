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
    assert c["status"] == "FROZEN_ATTEMPT1_READY_FOR_DEVELOPMENT_VALIDATION"
    assert c["candidate_family"] == admission["candidate_family"]
    assert ledger["attempts_used"] == 0
    assert ledger["attempts"] == []
    assert c["attempt_budget"]["attempts_used"] == 0
    assert c["attempt_budget"]["this_artifact_consumes_attempt"] is False
    assert c["attempt_budget"]["attempt_1_scoring_allowed"] is True
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
        "final_hardened_implementation_identity",
        "predictive_acceptance_thresholds",
    }
    assert all(value is None for value in unresolved.values())
    assert len(c["blocker_codes"]) == 2
    for key, value in c["authority"].items():
        if key == "research_contract":
            assert value is True
        else:
            assert value is False


def _git_blob_sha(path: Path) -> str:
    import hashlib
    raw = path.read_bytes()
    return hashlib.sha1(f"blob {len(raw)}\\0".encode() + raw).hexdigest()


def test_issue_693_freezes_rng_family_and_simulation_count_but_not_root_seed() -> None:
    c = _load(CONTRACT)
    a1 = c["attempt1_issue_binding"]
    assert a1["issue"] == 693
    assert a1["rng_algorithm"] == "NUMPY_PCG64"
    assert a1["seed_derivation"] == "NUMPY_SEEDSEQUENCE_EXPLICIT_INTEGER_ROOT_DETERMINISTIC_PER_GAME_PER_PATH"
    assert a1["root_seed"] == 15264549103493747052
    assert a1["simulation_count_paths_per_game"] == 50000
    assert a1["absolute_simulation_floor_paths_per_game"] == 10000
    assert a1["chronological_walk_forward_required"] is True
    assert a1["shuffled_rows_forbidden"] is True
    assert a1["calibrators_fit_on_training_only"] is True
    assert a1["reused_history_role"] == "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT"
    assert a1["no_fresh_untouched_population_terminal_state"] == "INSUFFICIENT_FRESH_UNTOUCHED_EVIDENCE"


def test_governance_provenance_uses_verifiable_ids_without_unverified_body_hash() -> None:
    c = _load(CONTRACT)
    p = c["governance_provenance"]
    assert p["human_policy_selection_issue"] == 616
    assert p["human_policy_selection_comment_id"] == 5662476744
    assert "human_policy_selection_body_sha256" not in p
    assert p["attempt0_design_issue"] == 620
    assert p["attempt0_finalization_comment_id"] == 5664137348
    assert p["attempt0_merge_commit"] == "7ed79c51e790d393108864513c34dd296d9fd175"


def test_attempt1_code_identity_stays_blocked_until_rng_hardening_is_canonical() -> None:
    c = _load(CONTRACT)
    identity = c["implementation_identity"]
    assert identity["status"] == "PENDING_POST_RNG_HARDENING_BINDING"
    assert identity["required_successor_pr"] == 1516
    assert identity["exact_code_identity_frozen_for_attempt1"] is False
    assert "V2K_FINAL_IMPLEMENTATION_IDENTITY_NOT_FROZEN" in c["blocker_codes"]


def test_attempt1_fold_geometry_is_expanding_chronological_and_leakage_closed() -> None:
    c = _load(CONTRACT)
    plan = c["attempt1_issue_binding"]["fold_plan"]
    assert plan["policy"] == "EXPANDING_SEASON_WALK_FORWARD_V1"
    assert plan["population_seasons"] == list(range(2018, 2026))
    assert plan["minimum_training_seasons"] == 3
    assert plan["shuffle"] is False
    assert plan["test_season_may_influence_fit"] is False
    assert plan["calibrator_fit_scope"] == "TRAINING_SEASONS_ONLY_WITHIN_EACH_FOLD"
    assert plan["role"] == "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT"
    folds = plan["folds"]
    assert [f["test_season"] for f in folds] == [2021, 2022, 2023, 2024, 2025]
    for fold in folds:
        test_season = fold["test_season"]
        assert fold["train_seasons"] == list(range(2018, test_season))
        assert test_season not in fold["train_seasons"]


def test_root_seed_is_identity_derived_before_scoring() -> None:
    import hashlib
    c = _load(CONTRACT)
    a1 = c["attempt1_issue_binding"]
    binding = a1["root_seed_derivation"]
    digest = hashlib.sha256(binding["input"].encode("utf-8")).digest()
    expected = int.from_bytes(digest[:8], "big", signed=False)
    assert binding["method"] == "UINT64_BIG_ENDIAN_FIRST_8_BYTES_OF_SHA256_UTF8"
    assert hashlib.sha256(binding["input"].encode("utf-8")).hexdigest() == binding["sha256"]
    assert expected == binding["output_integer"] == a1["root_seed"] == 15264549103493747052
    assert binding["performance_data_used"] is False
