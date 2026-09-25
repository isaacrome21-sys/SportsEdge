import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

ROOT=Path(__file__).resolve().parents[1]
RUNNER_PATH=ROOT/"scripts/run_cfb_candidate_bakeoff.py"


def _load_runner():
    spec=importlib.util.spec_from_file_location("run_cfb_candidate_bakeoff_v3_test",RUNNER_PATH)
    module=importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestCFBCandidateBakeoffRunnerV3(TestCase):
    def test_runner_uses_v3_and_frozen_dispersion_prereg(self):
        runner=_load_runner()
        cfg=json.loads((ROOT/"config/cfb_candidate_bakeoff_evaluator_v3.json").read_text())
        prereg=json.loads((ROOT/"config/cfb_dispersion_only_prereg_v1.json").read_text())
        runner._verify_v3_bindings(cfg,prereg)
        source=RUNNER_PATH.read_text()
        self.assertIn("candidate_bakeoff_v3 import evaluate_cfb_candidate_bakeoff_v3",source)
        self.assertNotIn("candidate_bakeoff_v2 import evaluate_cfb_candidate_bakeoff_v2",source)
        self.assertIn("--private-capture-out",source)

    def test_private_capture_path_must_be_outside_repository(self):
        runner=_load_runner()
        with self.assertRaisesRegex(SystemExit,"CFB_BAKEOFF_CAPTURE_PUBLIC_REPO_PATH_FORBIDDEN"):
            runner._assert_private_capture_path(ROOT/"artifacts/cfb/private_capture.json")
        with TemporaryDirectory() as tmp:
            runner._assert_private_capture_path(Path(tmp)/"private_capture.json")

    def test_workflow_keeps_capture_in_runner_temp_and_out_of_upload_list(self):
        workflow=(ROOT/".github/workflows/cfb-reconstructed-selection-materialize.yml").read_text()
        private_arg='--private-capture-out "$RUNNER_TEMP/cfb_candidate_bakeoff_private_capture.json"'
        self.assertIn(private_arg,workflow)
        self.assertIn("CFB_BAKEOFF_PRIVATE_CAPTURE_PUBLIC_PATH_FORBIDDEN",workflow)
        upload=workflow.split("Upload public reconstructed-selection attestations and model proposal only",1)[1]
        self.assertNotIn("cfb_candidate_bakeoff_private_capture.json",upload)

    def test_attempt_budget_still_unspent(self):
        parent=json.loads((ROOT/"config/cfb_model_selection_policy_v1.json").read_text())
        prereg=json.loads((ROOT/"config/cfb_model_candidate_prereg_v1.json").read_text())
        self.assertEqual(parent["attempts_consumed"],0)
        self.assertEqual(prereg["governance"]["attempts_consumed"],0)
        self.assertFalse(prereg["governance"]["evaluation_performed"])


if __name__=="__main__":
    import unittest
    unittest.main()
