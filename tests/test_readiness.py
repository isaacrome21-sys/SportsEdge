import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.readiness import audit_readiness


class ReadinessTests(unittest.TestCase):
    def test_checked_in_registry_reports_hits_tb_runnable_but_not_deployed(self):
        out = audit_readiness()
        rows = {x["market"]: x for x in out["markets"]}
        for market in ("HITS", "TOTAL_BASES"):
            self.assertTrue(rows[market]["runtime_engine"])
            self.assertTrue(rows[market]["runnable_live"])
            self.assertFalse(rows[market]["official_bet_enabled"])
            self.assertFalse(rows[market]["validation_complete"])
            self.assertIn("FIXTURE_CI_PENDING", rows[market]["blockers"])
            self.assertIn("historical_point_in_time", rows[market]["validation_missing"])

    def test_unknown_runtime_market_is_not_claimed_runnable(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "deployments.json"
            p.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"FOO": {"eligible": False, "stage": "VALIDATED_MATH", "reason": "test"}},
            }))
            out = audit_readiness(p)
        row = out["markets"][0]
        self.assertFalse(row["runtime_engine"])
        self.assertFalse(row["runnable_live"])
        self.assertIn("NO_RUNTIME_ENGINE", row["blockers"])

    def test_eligible_market_stays_officially_blocked_without_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "deployments.json"
            floors = root / "floors.json"
            validation = root / "validation.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"HITS": {"eligible": True, "stage": "PRODUCTION", "reason": "test"}},
            }))
            floors.write_text(json.dumps({
                "truth_gate": {"edge_floors": {"HITS": {"status": "FROZEN", "value": 0.02}}}
            }))
            validation.write_text(json.dumps({
                "required_gates": ["historical_point_in_time", "untouched_holdout"],
                "markets": {"HITS": {"historical_point_in_time": "PASS"}},
            }))
            out = audit_readiness(registry, floors_path=floors, validation_path=validation)
        row = out["markets"][0]
        self.assertTrue(row["runnable_live"])
        self.assertFalse(row["validation_complete"])
        self.assertFalse(row["official_bet_enabled"])
        self.assertIn("VALIDATION_UNTOUCHED_HOLDOUT_PENDING", row["blockers"])

    def test_official_enablement_requires_every_validation_gate_pass(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "deployments.json"
            floors = root / "floors.json"
            validation = root / "validation.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"HITS": {"eligible": True, "stage": "PRODUCTION", "reason": "test"}},
            }))
            floors.write_text(json.dumps({
                "truth_gate": {"edge_floors": {"HITS": {"status": "FROZEN", "value": 0.02}}}
            }))
            validation.write_text(json.dumps({
                "required_gates": ["historical_point_in_time", "untouched_holdout"],
                "markets": {"HITS": {
                    "historical_point_in_time": {"status": "PASS", "evidence": "fixture"},
                    "untouched_holdout": {"status": "PASS", "evidence": "fixture"}
                }},
            }))
            out = audit_readiness(registry, floors_path=floors, validation_path=validation)
        row = out["markets"][0]
        self.assertTrue(row["validation_complete"])
        self.assertTrue(row["official_bet_enabled"])


if __name__ == "__main__":
    unittest.main()
