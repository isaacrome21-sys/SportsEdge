import json
from pathlib import Path

MARKER = Path("config/research/nfl_score_counts_attempt1_dispatch_v1.json")
WORKFLOW = Path(".github/workflows/nfl-score-counts-attempt1-main-trigger.yml")


def test_attempt1_marker_is_exact_and_research_only():
    x = json.loads(MARKER.read_text(encoding="utf-8"))
    assert x["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT1_DISPATCH_V1"
    assert x["status"] == "ARMED_SINGLE_MAIN_PUSH"
    assert x["attempt_number"] == 1
    assert x["confirmation"] == "CONSUME_SCORE_COUNTS_ATTEMPT_1"
    assert x["rules"]["trigger_only_when_this_marker_lands_on_main"] is True
    assert x["rules"]["backfill"] is False
    assert x["rules"]["market_data_for_model_fit"] is False
    assert x["authority"]["creates_model_p"] is False
    assert x["authority"]["official"] is False


def test_attempt1_trigger_is_main_push_marker_scoped_not_pr_scoped():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "branches:" in text and "- main" in text
    assert "nfl_score_counts_attempt1_dispatch_v1.json" in text
    assert "pull_request:" not in text
    assert "--attempt-number 1" in text
    assert "--confirm CONSUME_SCORE_COUNTS_ATTEMPT_1" in text



def test_prefit_failure_receipt_marks_attempt_unspent_and_retry_bound():
    failure = json.loads(
        Path("config/research/nfl_score_counts_attempt1_prefit_failure_v1.json").read_text(
            encoding="utf-8"
        )
    )
    marker = json.loads(MARKER.read_text(encoding="utf-8"))
    assert failure["workflow_run_id"] == 37333803086
    assert failure["stage"] == "TRAINING_ROW_MATERIALIZATION"
    assert failure["attempt_accounting"]["fit_artifact_created"] is False
    assert failure["attempt_accounting"]["development_gate_evaluated"] is False
    assert failure["attempt_accounting"]["attempt_consumed"] is False
    assert marker["implementation_retry"]["prior_run_id"] == failure["workflow_run_id"]
    assert marker["implementation_retry"]["prior_attempt_consumed"] is False
