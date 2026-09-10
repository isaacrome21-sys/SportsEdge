from pathlib import Path

from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH


def test_builder_and_runner_share_canonical_artifact_path() -> None:
    assert DEFAULT_CFB_MODEL_ARTIFACT_PATH == Path("models/cfb_joint_v1.json")
    builder = Path("scripts/build_cfb_model_artifact.py").read_text(encoding="utf-8")
    runner = Path("scripts/run_cfb_auto.py").read_text(encoding="utf-8")
    import_line = "from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH"
    assert import_line in builder
    assert import_line in runner
    assert "default=DEFAULT_CFB_MODEL_ARTIFACT_PATH" in builder
    assert "default=DEFAULT_CFB_MODEL_ARTIFACT_PATH" in runner
    assert 'default=Path("config/cfb_model_artifact.json")' not in builder
    assert 'default=Path("config/cfb_model_artifact.json")' not in runner
