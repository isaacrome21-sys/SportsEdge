from pathlib import Path

PATH = Path(".github/workflows/nfl-v2k-attempt2-dispatch-bridge.yml")


def test_attempt2_dispatch_bridge_is_owner_exact_and_zero_model_surface():
    text = PATH.read_text(encoding="utf-8")
    assert "github.actor == github.repository_owner" in text
    assert "github.event.issue.number == 1539" in text
    assert "github.event.comment.body == 'CONSUME_ATTEMPT_2'" in text
    assert "actions: write" in text
    assert "nfl-v2k-attempt2-development-validation.yml/dispatches" in text
    assert "-f ref=main" in text
    assert "inputs[confirm]=CONSUME_ATTEMPT_2" in text
    assert "run_nfl_v2k_attempt2.py simulate" not in text
    assert "paths 50000" not in text
    assert "root_seed" not in text
