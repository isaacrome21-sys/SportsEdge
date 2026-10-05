import json
from pathlib import Path

PATH = Path("config/research/nfl_prop_usage_v1_2025_final.json")


def test_2025_prop_window_is_spent_without_statistical_verdict():
    value = json.loads(PATH.read_text())
    assert value["status"] == "VALIDATION_WINDOW_SPENT_TECHNICAL_FAILURE_NO_RESULT"
    assert value["window_spent"] is True
    assert value["second_look_allowed"] is False
    assert value["retune_allowed"] is False
    assert value["statistical_verdict"] is None
    assert value["model_scoring_completed"] is False
    run = value["canonical_execution"]
    assert run["workflow_run_id"] == 36976714292
    assert run["workflow_artifact_id"] == 11213747098
    assert run["spend_receipt_written_before_target_source_access"] is True
    assert run["failure"] == "HTTP_404_PLAYER_STATS_2025"
    assert run["calibration_computed"] is False
    assert run["brier_computed"] is False
    assert value["policy"]["2025_retry_forbidden"] is True
    assert value["policy"]["fresh_predeclared_window_required_for_any_future_validation"] is True
    assert not any(v for k, v in value["authority"].items() if k != "research_only")
