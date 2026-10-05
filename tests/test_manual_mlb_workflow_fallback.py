from pathlib import Path

WORKFLOW = Path(".github/workflows/manual-mlb-snapshot.yml")


def test_code_only_push_without_live_slate_falls_back_to_regression_fixture():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "use_regression_fixture()" in text
    assert "NO_CURRENT_OR_FUTURE_MLB_SNAPSHOT_ON_CODE_PUSH" in text
    assert "NO_DATED_MLB_SNAPSHOT_ON_CODE_PUSH" in text
    assert 'if [[ "$EVENT_NAME" == "push" ]]' in text
    assert 'echo "live=false" >> "$GITHUB_OUTPUT"' in text


def test_manual_dispatch_without_usable_slate_still_fails_closed():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'echo "NO_CURRENT_OR_FUTURE_MLB_SNAPSHOT" >&2' in text
    assert 'echo "DATED_INPUT_NOT_LOADED: no dated manual_inputs/mlb snapshot" >&2' in text
