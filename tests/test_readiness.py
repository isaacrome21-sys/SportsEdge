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
            self.assertTrue(rows[market]["feature_contract_declared"])
            self.assertFalse(rows[market]["feature_realization_complete"])
            self.assertEqual(rows[market]["feature_realization_status"], "PARTIAL")
            self.assertTrue(rows[market]["runnable_live"])
            self.assertFalse(rows[market]["official_bet_enabled"])
            self.assertFalse(rows[market]["validation_complete"])
            self.assertIn("FIXTURE_CI_PENDING", rows[market]["blockers"])
            self.assertIn("historical_point_in_time", rows[market]["validation_missing"])

    def test_every_checked_in_market_has_declared_contract_but_realization_is_separate(self):
        out = audit_readiness()
        missing = [x["market"] for x in out["markets"] if not x["feature_contract_declared"]]
        self.assertEqual(missing, [])
        self.assertLess(out["summary"]["feature_realization_complete"], out["summary"]["feature_contract_complete"])

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
        self.assertFalse(row["feature_contract_declared"])
        self.assertFalse(row["feature_realization_complete"])
        self.assertFalse(row["runnable_live"])
        self.assertIn("NO_RUNTIME_ENGINE", row["blockers"])
        self.assertIn("NO_DECLARED_FEATURE_CONTRACT", row["blockers"])

    def test_eligible_market_stays_officially_blocked_without_validation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "deployments.json"
            floors = root / "floors.json"
            validation = root / "validation.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"HITS": {"eligible": True, "stage": "DEPLOYED", "reason": "test"}},
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

    def test_validation_pass_is_not_enough_without_feature_realization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "deployments.json"
            floors = root / "floors.json"
            validation = root / "validation.json"
            realization = root / "realization.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"HITS": {"eligible": True, "stage": "DEPLOYED", "reason": "test"}},
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
            realization.write_text(json.dumps({"schema_version": 1, "markets": {"HITS": {"status": "PARTIAL", "gaps": ["test_gap"]}}}))
            out = audit_readiness(
                registry, floors_path=floors, validation_path=validation,
                feature_realization_path=realization,
            )
        row = out["markets"][0]
        self.assertTrue(row["validation_complete"])
        self.assertFalse(row["feature_realization_complete"])
        self.assertFalse(row["official_bet_enabled"])
        self.assertIn("FEATURE_REALIZATION_PARTIAL", row["blockers"])

    def test_official_enablement_requires_validation_and_complete_feature_realization(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registry = root / "deployments.json"
            floors = root / "floors.json"
            validation = root / "validation.json"
            realization = root / "realization.json"
            registry.write_text(json.dumps({
                "schema_version": 1,
                "markets": {"HITS": {"eligible": True, "stage": "DEPLOYED", "reason": "test"}},
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
            realization.write_text(json.dumps({"schema_version": 1, "markets": {"HITS": {"status": "COMPLETE", "gaps": []}}}))
            out = audit_readiness(
                registry, floors_path=floors, validation_path=validation,
                feature_realization_path=realization,
            )
        row = out["markets"][0]
        self.assertTrue(row["validation_complete"])
        self.assertTrue(row["feature_realization_complete"])
        self.assertTrue(row["official_bet_enabled"])


if __name__ == "__main__":
    unittest.main()
