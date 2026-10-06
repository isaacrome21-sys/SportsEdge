from pathlib import Path

WORKFLOW = Path(".github/workflows/nfl-score-counts-attempt3-recovery-trigger.yml")
ORIGINAL = Path("config/research/nfl_score_counts_attempt3_dispatch_v1.json")
RECOVERY = Path("config/research/nfl_score_counts_attempt3_recovery_dispatch_v1.json")


def test_attempt3_recovery_trigger_runs_only_on_explicit_recovery_marker_push():
    assert WORKFLOW.is_file()
    assert ORIGINAL.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:" in text
    assert "branches:" in text and "- main" in text
    assert "nfl_score_counts_attempt3_recovery_dispatch_v1.json" in text
    assert "pull_request:" not in text
    assert "--attempt-number 3" in text
    assert "--confirm CONSUME_SCORE_COUNTS_ATTEMPT_3" in text


def test_attempt3_recovery_trigger_revalidates_original_authorization_and_identity():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'x["code_identity"] == code_identity()' in text
    assert 'r["original_dispatch_sha256"] == sha256_file(original)' in text
    assert 'assert not result.exists()' in text
    assert 'x["rules"]["no_fourth_attempt"] is True' in text
    assert 'r["rules"]["no_fourth_attempt"] is True' in text
    assert 'r["rules"]["thresholds_unchanged"] is True' in text
    assert 'r["rules"]["backfill"] is False' in text
