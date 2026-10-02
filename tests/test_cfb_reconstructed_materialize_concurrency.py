from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZE = ROOT / ".github/workflows/cfb-reconstructed-selection-materialize.yml"
BRIDGE = ROOT / ".github/workflows/cfb-reconstructed-materialize-push-bridge.yml"


def test_provider_consuming_materialization_is_serialized() -> None:
    text = MATERIALIZE.read_text(encoding="utf-8")
    materialize = text.split("  materialize:", 1)[1]
    assert "group: cfb-reconstructed-selection-materialize-runtime" in materialize
    assert "cancel-in-progress: false" in materialize


def test_push_bridge_does_not_dispatch_while_materializer_is_active() -> None:
    text = BRIDGE.read_text(encoding="utf-8")
    assert "group: cfb-reconstructed-materialize-push-bridge" in text
    assert "cancel-in-progress: false" in text
    assert "gh run list" in text
    assert "cfb-reconstructed-selection-materialize.yml" in text
    assert '.status == "queued" or .status == "in_progress"' in text
    assert "CFB_RECONSTRUCTED_MATERIALIZE_DISPATCH_SKIPPED" in text


def test_bridge_can_only_request_materialize_only() -> None:
    text = BRIDGE.read_text(encoding="utf-8")
    assert "-f evaluation_mode=MATERIALIZE_ONLY" in text
    assert "CONSUME_ALL_FOUR_CFB_ATTEMPTS" not in text
