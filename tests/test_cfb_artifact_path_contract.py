from pathlib import Path

from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH


def test_canonical_cfb_model_artifact_path() -> None:
    assert DEFAULT_CFB_MODEL_ARTIFACT_PATH == Path("models/cfb_joint_v1.json")


def test_builder_and_auto_runner_use_canonical_artifact_path() -> None:
    for script in (Path("scripts/build_cfb_model_artifact.py"), Path("scripts/run_cfb_auto.py")):
        text = script.read_text(encoding="utf-8")
        assert "DEFAULT_CFB_MODEL_ARTIFACT_PATH" in text
        assert "default=DEFAULT_CFB_MODEL_ARTIFACT_PATH" in text
        assert "config/cfb_model_artifact.json" not in text
