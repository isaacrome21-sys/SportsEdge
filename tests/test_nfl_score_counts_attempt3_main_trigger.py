from pathlib import Path

WORKFLOW = Path(".github/workflows/nfl-score-counts-attempt3-main-trigger.yml")
MARKER = Path("config/research/nfl_score_counts_attempt3_dispatch_v1.json")


def test_attempt3_trigger_workflow_is_inert_until_marker_lands_on_main():
    assert WORKFLOW.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "branches:" in text and "- main" in text
    assert "nfl_score_counts_attempt3_dispatch_v1.json" in text
    assert "pull_request:" not in text
    assert "--attempt-number 3" in text
    assert "--confirm CONSUME_SCORE_COUNTS_ATTEMPT_3" in text

    # The trigger workflow may coexist with an armed marker on the dispatch
    # branch. It is still inert there because the workflow only runs on a push
    # of that marker to protected main. Once the marker exists, validate its
    # one-shot/main-only contract instead of treating existence as a failure.
    if MARKER.exists():
        import json
        marker = json.loads(MARKER.read_text(encoding="utf-8"))
        assert marker["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT3_DISPATCH_V1"
        assert marker["status"] == "ARMED_SINGLE_MAIN_PUSH"
        assert marker["attempt_number"] == 3
        assert marker["confirmation"] == "CONSUME_SCORE_COUNTS_ATTEMPT_3"
        assert marker["rules"]["trigger_only_when_this_marker_lands_on_main"] is True
        assert marker["rules"]["no_fourth_attempt"] is True


def test_attempt3_trigger_validates_frozen_identity_before_execution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'x["prereg_sha256"] == sha256_file(prereg)' in text
    assert 'x["attempt_2_result_sha256"] == sha256_file(attempt2)' in text
    assert 'x["code_identity"] == code_identity()' in text
    assert 'x["rules"]["no_fourth_attempt"] is True' in text
    assert 'x["rules"]["thresholds_unchanged"] is True' in text
