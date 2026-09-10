from pathlib import Path
import unittest

from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH


class CFBArtifactPathContractTests(unittest.TestCase):
    def test_builder_and_runner_share_canonical_artifact_path(self) -> None:
        self.assertEqual(DEFAULT_CFB_MODEL_ARTIFACT_PATH, Path("models/cfb_joint_v1.json"))
        builder = Path("scripts/build_cfb_model_artifact.py").read_text(encoding="utf-8")
        runner = Path("scripts/run_cfb_auto.py").read_text(encoding="utf-8")
        import_line = "from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH"
        self.assertIn(import_line, builder)
        self.assertIn(import_line, runner)
        self.assertIn("default=DEFAULT_CFB_MODEL_ARTIFACT_PATH", builder)
        self.assertIn("default=DEFAULT_CFB_MODEL_ARTIFACT_PATH", runner)
        self.assertNotIn('default=Path("config/cfb_model_artifact.json")', builder)
        self.assertNotIn('default=Path("config/cfb_model_artifact.json")', runner)


if __name__ == "__main__":
    unittest.main()
