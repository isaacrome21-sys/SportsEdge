from pathlib import Path
import unittest

import scripts.build_cfb_model_artifact as builder


class CFBArtifactPathContractTests(unittest.TestCase):
    def test_builder_default_matches_live_runner_contract(self):
        expected = Path("models/cfb_joint_v1.json")
        self.assertEqual(builder.DEFAULT_CFB_MODEL_ARTIFACT_PATH, expected)

        runner_source = Path("scripts/run_cfb_auto.py").read_text(encoding="utf-8")
        self.assertIn(
            'parser.add_argument("--model-artifact", type=Path, default=Path("models/cfb_joint_v1.json"))',
            runner_source,
        )

    def test_legacy_config_path_is_not_builder_default(self):
        self.assertNotEqual(
            builder.DEFAULT_CFB_MODEL_ARTIFACT_PATH,
            Path("config/cfb_model_artifact.json"),
        )


if __name__ == "__main__":
    unittest.main()
