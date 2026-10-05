from __future__ import annotations

import json
from pathlib import Path


POLICY = Path("config/research/nfl_score_counts_g1_attempt2_fg_addendum_v1.json")


def test_attempt2_fg_prereg_is_frozen_after_real_attempt1_failure():
    policy = json.loads(POLICY.read_text())
    assert policy["status"] == "FROZEN_BEFORE_ATTEMPT2_IMPLEMENTATION_OR_HISTORICAL_SCORING"
    assert policy["attempt_accounting"] == {
        "max_materially_distinct_attempts": 3,
        "attempts_consumed_before_this_spec": 1,
        "attempts_remaining_before_this_spec": 2,
        "this_spec_if_evaluated_consumes_attempt": 2,
        "thresholds_unchanged": True,
        "attempt1_result_preserved": True,
    }
    bound = policy["attempt1_binding"]
    assert bound["workflow_run_id"] == 37336963800
    assert bound["workflow_artifact_id"] == 11358403155
    assert bound["fit_artifact_payload_sha256"] == "882861e89602432aa8622f78e89fc84c30602c0e7f079235dad73f3980526520"
    assert bound["source_manifest_sha256"] == "5394e39892436a63816f5d3b499250c7764875f385646c71ed851e560db8187b"
    assert bound["status"] == "DEVELOPMENT_ATTEMPT_FAIL"
    assert bound["touchdown_gate"]["fold_wins"] == 5
    assert bound["touchdown_gate"]["pass"] is True
    assert bound["field_goal_gate"]["fold_wins"] == 0
    assert bound["field_goal_gate"]["pass"] is False


def test_attempt2_changes_only_field_goal_component_and_preserves_gate():
    policy = json.loads(POLICY.read_text())
    reason = policy["reason_for_attempt2"]
    assert reason["scope"] == "FIELD_GOAL_COMPONENT_ONLY"
    assert reason["touchdown_component_changed"] is False

    spec = policy["attempt2_field_goal_specification"]
    assert spec["decomposition"].startswith("EXPECTED_MADE_FIELD_GOALS")
    assert spec["attempt_model"]["target"] == "FIELD_GOAL_ATTEMPTS"
    assert spec["attempt_model"]["alpha_grid"] == [0.1, 1.0, 10.0, 100.0]
    assert spec["make_rate"]["prior_strength_attempts"] == 25
    assert spec["development_gate"]["evaluation_target"] == "MADE_FIELD_GOALS"
    assert spec["development_gate"]["minimum_fold_wins"] == 3
    assert spec["development_gate"]["pooled_candidate_deviance_must_be_lower_than_baseline"] is True
    assert policy["preserved_contract"]["touchdown_model_specification"] == "UNCHANGED_FROM_ATTEMPT1"
    assert policy["preserved_contract"]["market_inputs_forbidden"] is True
    assert policy["preserved_contract"]["backfill_allowed"] is False
