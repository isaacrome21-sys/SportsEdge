from pathlib import Path

WORKFLOW = Path(".github/workflows/nfl-score-counts-attempt3-main-trigger.yml")
MARKER = Path("config/research/nfl_score_counts_attempt3_dispatch_v1.json")


def test_attempt3_trigger_workflow_is_inert_without_marker():
    assert WORKFLOW.is_file()
    assert not MARKER.exists()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "branches:" in text and "- main" in text
    assert "nfl_score_counts_attempt3_dispatch_v1.json" in text
    assert "pull_request:" not in text
    assert "--attempt-number 3" in text
    assert "--confirm CONSUME_SCORE_COUNTS_ATTEMPT_3" in text


def test_attempt3_trigger_validates_frozen_identity_before_execution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'x["prereg_sha256"] == sha256_file(prereg)' in text
    assert 'x["attempt_2_result_sha256"] == sha256_file(attempt2)' in text
    assert 'x["code_identity"] == code_identity()' in text
    assert 'x["rules"]["no_fourth_attempt"] is True' in text
    assert 'x["rules"]["thresholds_unchanged"] is True' in text
