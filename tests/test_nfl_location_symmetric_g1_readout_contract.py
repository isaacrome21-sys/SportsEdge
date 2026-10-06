import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/research/nfl_location_symmetric_g1_readout_execution_v1.json"
WORKFLOW = ROOT / ".github/workflows/nfl-location-symmetric-g1-readout.yml"


class NFLG1RealReadoutContractTests(unittest.TestCase):
    def test_execution_contract_is_zero_authority_and_push_only(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(cfg["schema"], "NFL_LOCATION_SYMMETRIC_G1_READOUT_EXECUTION_V1")
        self.assertEqual(cfg["status"], "FROZEN_BEFORE_FIRST_REAL_READOUT")
        self.assertTrue(cfg["pull_request_real_readout_forbidden"])
        self.assertFalse(cfg["retuning_after_readout"])
        self.assertFalse(cfg["market_fields_used_as_model_inputs"])
        self.assertFalse(any(
            value for key, value in cfg["authority"].items()
            if key != "research_only"
        ))
        self.assertTrue(cfg["authority"]["research_only"])

    def test_workflow_cannot_run_real_readout_on_pull_request(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(
            "if: github.event_name == 'push' && github.ref == 'refs/heads/main'",
            text,
        )
        self.assertIn(
            "python scripts/materialize_nfl_frozen_sources.py",
            text,
        )
        self.assertIn(
            "python scripts/run_nfl_location_symmetric_g1_readout.py",
            text,
        )
        self.assertIn(
            "--source-contract config/nfl_promotion_source_freeze_v1.json",
            text,
        )

    def test_readout_uses_exact_production_m2_source_surface(self):
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(
            cfg["source_contract"],
            "config/nfl_promotion_source_freeze_v1.json",
        )
        self.assertEqual(
            cfg["history_builder"],
            "sportsedge/sports/nfl/m2_history_policy.py::build_nfl_m2_history_rows",
        )
        self.assertEqual(cfg["source_seasons"], list(range(2016, 2026)))
        self.assertEqual(cfg["scored_outer_test_seasons"], [2021, 2022, 2023, 2024, 2025])


if __name__ == "__main__":
    unittest.main()
