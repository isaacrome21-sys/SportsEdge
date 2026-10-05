import json
from pathlib import Path

PATH = Path("config/research/nfl_prop_usage_v1_2026_forward_validation_lock.json")


def test_forward_lock_keeps_candidate_fixed_and_2025_closed():
    value = json.loads(PATH.read_text())
    assert value["status"] == "FROZEN_BEFORE_FORWARD_WEEK5_EVIDENCE"
    candidate = value["candidate_identity"]
    assert candidate["fit_artifact_sha256"] == "ef38c7101da0977f27b71a7cbbe40321149ee2e0fda3bb8371f04d8423c9c555"
    assert candidate["refit_allowed"] is False
    assert candidate["retune_allowed"] is False
    prior = value["prior_window_disposition"]
    assert prior["season"] == 2025
    assert prior["status"] == "SPENT_TECHNICAL_FAILURE_NO_RESULT"
    assert prior["retry_allowed"] is False


def test_forward_window_is_week5_plus_and_no_backfill():
    value = json.loads(PATH.read_text())
    window = value["forward_window"]
    assert window["season"] == 2026
    assert window["first_eligible_week"] == 5
    assert window["last_eligible_week"] == 18
    assert window["first_eligible_kickoff_utc"] == "2026-10-09T00:15:00Z"
    assert window["evidence_clock_starts_only_after_this_lock_is_merged_to_main"] is True
    assert window["prelock_rows_admissible"] is False
    assert window["weeks_1_through_4_admissible"] is False
    assert window["backfill_allowed"] is False


def test_forward_validation_gates_are_frozen_and_zero_authority():
    value = json.loads(PATH.read_text())
    assert value["validation_gates"]["calibration_max"] == 0.06
    assert value["validation_gates"]["required_scopes"] == [
        "passing_yards", "rushing_yards", "receiving_yards", "pooled"
    ]
    assert value["validation_gates"]["evaluation_timing"] == "AFTER_WEEK_18_WINDOW_CLOSE_ONLY"
    assert value["decision_snapshot"]["book"] == "draftkings"
    assert value["decision_snapshot"]["paired_over_under_required"] is True
    assert value["close_snapshot"]["paired_over_under_required"] is True
    assert not any(v for k, v in value["authority"].items() if k != "research_only")
