from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "sportsedge/sports/nfl/NFL_V2J_FROZEN_FAILURE_RECEIPT_V1.json"


def _load() -> dict:
    return json.loads(RECEIPT.read_text())


def test_receipt_binds_exact_successor_and_adjudicator() -> None:
    p = _load()
    assert p["status"] == "FROZEN_PREDICTIVE_FAILURE_ZERO_AUTHORITY"
    assert p["upstream"]["workflow_run_id"] == 34790748032
    assert p["upstream"]["head_sha"] == "685a9f3bf8bb6e1c59c007db2b8205ca8a59f527"
    assert p["adjudication"]["workflow_run_id"] == 34809137480
    assert p["adjudication"]["adjudicator_git_sha"] == "6a5dece6b5a51c511731217a213c912f013bb53e"
    assert p["adjudication"]["verdict"] == "V2J_FROZEN_GATES_FAIL_ZERO_AUTHORITY"
    assert p["adjudication"]["candidate_rejected_by_frozen_gates"] is True


def test_rejected_v2j_is_paper_zero_units_and_has_no_authority() -> None:
    p = _load()
    lifecycle = p["lifecycle"]
    assert lifecycle["v2j_state"] == "REJECTED"
    assert lifecycle["surface"] == "PAPER"
    assert lifecycle["stake_units"] == 0
    assert lifecycle["bettor_facing_model_p_allowed"] is False
    assert lifecycle["v2k_research_may_advance"] is True
    assert lifecycle["v2k_automatically_activated"] is False
    assert lifecycle["v2k_attempt_consumed_by_this_receipt"] is False
    assert all(value is False for value in p["authority"].values())


def test_failure_is_not_reinterpreted_as_partial_pass() -> None:
    p = _load()
    assert p["market_results"]["spread"]["pass"] is False
    assert p["market_results"]["total"]["pass"] is False
    assert p["adjudication"]["frozen_gate_pass"] is False
    assert p["adjudication"]["historical_predictive_pass"] is False
    assert p["adjudication"]["calibration_pass"] is False
    assert p["adjudication"]["signed_key_gate_pass"] is False


def test_v2k_next_boundary_stays_fail_closed() -> None:
    p = _load()
    boundary = p["next_boundary"]
    assert boundary["candidate_family"] == "NFL_V2K_DRIVE_HIERARCHICAL_JOINT_G1"
    assert boundary["development_validation_scoring_remains_blocked_until_folds_sources_features_rng_seed_simulation_count_thresholds_and_attempt_record_are_frozen"] is True
    assert boundary["structural_gate_requires_strict_improvement_in_both_calibration_slope_error_and_signed_key_mass_metric"] is True
    assert boundary["threshold_weakening_forbidden"] is True
    assert boundary["v2j_readout_values_for_v2k_tuning_forbidden"] is True
