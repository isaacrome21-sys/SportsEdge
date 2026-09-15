from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts/build_nfl_attempt9_runtime_artifact.py"
WORKFLOW = ROOT / ".github/workflows/whole-model-train.yml"


def _load_builder():
    spec = importlib.util.spec_from_file_location("attempt9_runtime_builder", BUILDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("builder import failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_help(module_name: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", module_name, "--help"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class WholeModelTrainPlumbingTest(unittest.TestCase):
    def test_nfl_preflight_supports_direct_and_module_help(self):
        direct = subprocess.run(
            [sys.executable, "scripts/nfl_2026_provider_preflight.py", "--help"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        module = _module_help("scripts.nfl_2026_provider_preflight")
        self.assertEqual(direct.returncode, 0, direct.stderr)
        self.assertEqual(module.returncode, 0, module.stderr)

    def test_package_dependent_workflow_scripts_use_module_mode(self):
        modules = (
            "scripts.build_ufc_training_artifact",
            "scripts.audit_cfb_model_selection_prereg",
            "scripts.audit_cfb_pit_readiness",
        )
        for module_name in modules:
            with self.subTest(module=module_name):
                result = _module_help(module_name)
                self.assertEqual(result.returncode, 0, result.stderr)

        workflow = WORKFLOW.read_text(encoding="utf-8")
        expected = (
            "python -m scripts.build_ufc_training_artifact",
            "python -m scripts.audit_cfb_model_selection_prereg",
            "python -m scripts.audit_cfb_pit_readiness",
        )
        forbidden = (
            "python scripts/build_ufc_training_artifact.py",
            "python scripts/audit_cfb_model_selection_prereg.py",
            "python scripts/audit_cfb_pit_readiness.py",
        )
        for command in expected:
            self.assertIn(command, workflow)
        for command in forbidden:
            self.assertNotIn(command, workflow)

    def test_pga_check_uses_existing_live_runner_symbol(self):
        from sportsedge.pga.runner import run_live_pga_model

        self.assertTrue(callable(run_live_pga_model))
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("from sportsedge.pga.runner import run_live_pga_model", workflow)
        self.assertNotIn("from sportsedge.pga.runner import run_pga", workflow)

    def test_manifest_requires_lane_artifacts_before_claiming_cfb_or_pga_success(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("READINESS_AUDIT_NOT_RUN", workflow)
        self.assertIn("READINESS_AUDIT_PARTIAL", workflow)
        self.assertIn("ENGINE_CHECK_NOT_RUN", workflow)
        self.assertIn("pga_engine_check.json", workflow)
        self.assertNotIn("'state':'READINESS_AUDITED_NO_ATTEMPT_SPENT',", workflow)
        self.assertNotIn("'state':'ENGINE_IMPORTABLE_AUTOMATIC_INPUT_BLOCKED',", workflow)

    def test_attempt9_public_source_is_exactly_pinned(self):
        cfg = json.loads((ROOT / "config/public_training_sources_v1.json").read_text())
        nfl = cfg["sources"]["nfl_attempt9"]
        self.assertEqual(nfl["commit"], "be9813d153e6694af4d98c7287a7db32225806ae")
        self.assertEqual(
            nfl["expected_sha256"],
            "59c8bea7e185dde9e6053a06c24c34f6e5a91dcaea3187c0d9bab12759bb05fb",
        )
        self.assertEqual(nfl["actions_run_id"], 34492360674)
        self.assertEqual(
            nfl["actions_artifact_digest"],
            "sha256:9c95c0cbefc2f99f6dec37fda01f58d2fcac0ad6770de2c9311fbf5ce40ea996",
        )

    def test_attempt9_historical_numeric_environment_records_knowns_and_unknowns(self):
        cfg = json.loads((ROOT / "config/public_training_sources_v1.json").read_text())
        nfl = cfg["sources"]["nfl_attempt9"]
        env = nfl["historical_numeric_environment"]
        self.assertEqual(env["azure_region"], "eastus2")
        self.assertEqual(env["python_version"], "3.12.14")
        self.assertEqual(env["numpy_version"], "2.5.3")
        self.assertEqual(env["runner_image_version"], "20260907.300.1")
        self.assertEqual(env["cpu_model"], "UNRECORDED_IN_ORIGINAL_RUN")
        self.assertEqual(env["blas_build"], "UNRECORDED_IN_ORIGINAL_RUN")
        self.assertEqual(env["openblas_coretype"], "UNRECORDED_IN_ORIGINAL_RUN")
        self.assertEqual(
            env["numpy_wheel"],
            "numpy-2.5.3-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
        )
        self.assertEqual(
            env["thread_environment"],
            {
                "OPENBLAS_NUM_THREADS": "UNRECORDED_IN_ORIGINAL_RUN",
                "OMP_NUM_THREADS": "UNRECORDED_IN_ORIGINAL_RUN",
                "MKL_NUM_THREADS": "UNRECORDED_IN_ORIGINAL_RUN",
            },
        )
        observations = nfl["numeric_compatibility_observations"]
        self.assertTrue(any(row["result"] == "COEFFICIENT_TEXT_MISMATCH_AT_LAST_ULPS" for row in observations))
        self.assertTrue(any(row["result"].startswith("ALL_TESTED_THREAD_COUNTS_REPRODUCED_EXACT") for row in observations))

    def test_attempt9_reconstruction_pins_compatibility_environment(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python-version: '3.12.14'", workflow)
        marker = "- name: Reconstruct exact frozen NFL attempt-9 runtime owner"
        self.assertIn(marker, workflow)
        step = workflow.split(marker, 1)[1].split("- name:", 1)[0]
        self.assertIn("OPENBLAS_CORETYPE: ZEN", step)
        self.assertIn("OPENBLAS_NUM_THREADS: '1'", step)
        self.assertIn("OMP_NUM_THREADS: '1'", step)
        self.assertIn("MKL_NUM_THREADS: '1'", step)

    def test_attempt9_prediction_digest_is_canonical(self):
        builder = _load_builder()
        values = builder.np.asarray([1.25, -2.5, 0.0], dtype=float)
        expected = hashlib.sha256(b"[1.25,-2.5,0.0]").hexdigest()
        self.assertEqual(builder._prediction_sha(values), expected)

    def test_attempt9_exact_coefficient_text_contract(self):
        builder = _load_builder()
        self.assertEqual(
            builder._float_list_json(builder.EXPECTED_COEFFICIENTS["margin"]),
            "[1.9219959071859163,-1.1939546971867534,-1.700049235015833,0.4894639011852299,2.051162351492163,-1.4712827317889383]",
        )
        self.assertEqual(
            builder._float_list_json(builder.EXPECTED_COEFFICIENTS["total"]),
            "[1.9674873702327231,1.4677035717536322,1.6205830069927165,1.2581489139175235,0.45966409421453325,0.3368500740711741]",
        )

    def test_attempt9_same_date_rows_do_not_see_same_date_results(self):
        builder = _load_builder()
        games = []
        for index in range(5):
            games.append({
                "date": f"2016-09-{index + 1:02d}",
                "id": f"prior-{index}",
                "home": "A",
                "away": "B",
                "hs": 20 + index,
                "as": 10 + index,
            })
        games.extend([
            {"date": "2016-10-01", "id": "same-1", "home": "A", "away": "B", "hs": 100, "as": 0},
            {"date": "2016-10-01", "id": "same-2", "home": "A", "away": "B", "hs": 0, "as": 100},
        ])
        x, margin, total, dates = builder.build_features(games)
        self.assertEqual(dates, ["2016-10-01", "2016-10-01"])
        self.assertEqual(x.shape, (2, 6))
        self.assertTrue(builder.np.array_equal(x[0], x[1]))
        self.assertEqual(margin.tolist(), [100.0, -100.0])
        self.assertEqual(total.tolist(), [100.0, 100.0])

    def test_public_source_registry_has_zero_authority(self):
        cfg = json.loads((ROOT / "config/public_training_sources_v1.json").read_text())
        self.assertFalse(cfg["authority"]["creates_model_p"])
        self.assertFalse(cfg["authority"]["changes_promotion"])
        self.assertFalse(cfg["authority"]["changes_truth_gate"])
        self.assertFalse(cfg["authority"]["changes_official"])
        self.assertFalse(cfg["authority"]["changes_staking"])


if __name__ == "__main__":
    unittest.main()