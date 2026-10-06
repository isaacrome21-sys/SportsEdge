from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cfb-reconstructed-selection-materialize.yml"
TRIGGER = ROOT / ".github" / "trigger-cfb-reconstructed-materialize-v2"


def test_push_bridge_is_materialize_only_and_scoped_to_request_file():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "push:\n    branches: [main]\n    paths:\n      - '.github/trigger-cfb-reconstructed-materialize-v2'" in text
    assert "github.event_name == 'workflow_dispatch' || github.event_name == 'repository_dispatch' || github.event_name == 'push'" in text

    # The model-evaluation step must remain dispatch-only. A push is allowed to
    # acquire/materialize reconstructed inputs but must never consume attempts.
    assert (
        "if: github.event_name == 'workflow_dispatch' "
        "&& steps.preflight.outputs.state == 'VERIFIED_BEFORE_FIRST_REPLAY_CALL' "
        "&& inputs.evaluation_mode == 'CONSUME_ALL_FOUR_CFB_ATTEMPTS'"
    ) in text

    request = TRIGGER.read_text(encoding="utf-8")
    assert "requested_mode=MATERIALIZE_ONLY" in request
    assert "no_evaluation_attempt=true" in request
    assert "no_backfill=true" in request
