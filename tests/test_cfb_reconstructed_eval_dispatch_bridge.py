import json
from pathlib import Path

WORKFLOW = Path(".github/workflows/cfb-reconstructed-eval-dispatch-bridge.yml")
MARKER = Path("config/research/cfb_reconstructed_eval_dispatch_v1.json")


def test_cfb_reconstructed_eval_bridge_is_inert_until_main_marker():
    assert WORKFLOW.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "- main" in text
    assert "cfb_reconstructed_eval_dispatch_v1.json" in text
    assert "pull_request:" not in text
    assert "CONSUME_ALL_FOUR_CFB_ATTEMPTS" in text
    assert "cfb-reconstructed-selection-materialize.yml" in text
    assert "materialization_must_exist_on_data" in text
    assert "attempts_consumed" in text and "== 0" in text

    if MARKER.exists():
        marker = json.loads(MARKER.read_text(encoding="utf-8"))
        assert marker["schema"] == "SPORTSEDGE_CFB_RECONSTRUCTED_EVAL_DISPATCH_V1"
        assert marker["status"] == "ARMED_SINGLE_MAIN_PUSH"
        assert marker["confirmation"] == "CONSUME_ALL_FOUR_CFB_ATTEMPTS"
        assert marker["rules"]["attempt_budget_must_be_fresh"] is True
        assert marker["rules"]["no_backfill"] is True


def test_cfb_reconstructed_eval_bridge_validates_all_frozen_bindings():
    text = WORKFLOW.read_text(encoding="utf-8")
    for key in (
        "candidate_prereg_sha256",
        "evaluator_v3_sha256",
        "final_fit_policy_sha256",
        "materializer_workflow_sha256",
    ):
        assert key in text
    assert 'bundle["status"] == "READY_FOR_CANDIDATE_EVALUATION"' in text
    assert 'acquisition["status"] == "ACQUISITION_COMPLETE_READY_FOR_SELECTION"' in text
    assert 'bundle["historical_pit_created"] is False' in text
    assert 'bundle["evaluation_performed"] is False' in text
