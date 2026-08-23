import json
import unittest
from pathlib import Path


class MLBMarketContractCoverageTests(unittest.TestCase):
    def _catalog_markets(self):
        raw = json.loads(Path("config/mlb_market_catalog.json").read_text())
        out = set()
        for key, rows in raw.items():
            if key == "schema_version" or not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, str):
                    out.add(row)
                elif isinstance(row, dict) and row.get("market"):
                    out.add(str(row["market"]))
        return out

    def test_every_catalog_market_has_feature_contract(self):
        catalog = self._catalog_markets()
        features = json.loads(Path("config/mlb_market_feature_requirements.json").read_text())
        self.assertEqual(catalog, set(features["markets"]))

    def test_every_catalog_market_has_validation_record(self):
        catalog = self._catalog_markets()
        validation = json.loads(Path("config/mlb_validation_evidence.json").read_text())
        self.assertEqual(catalog, set(validation["markets"]))

    def test_every_catalog_market_has_feature_realization_record(self):
        catalog = self._catalog_markets()
        realization = json.loads(Path("config/mlb_feature_realization.json").read_text())
        self.assertEqual(catalog, set(realization["markets"]))
        self.assertEqual(len(catalog), 27)
        allowed = {"COMPLETE", "PARTIAL", "MINIMAL", "PLANNED", "UNVERIFIED"}
        for market, row in realization["markets"].items():
            self.assertIn(row["status"], allowed, market)
            self.assertIsInstance(row.get("gaps"), list, market)

    def test_every_catalog_market_has_behavioral_disposition(self):
        catalog = self._catalog_markets()
        behavioral = json.loads(Path("config/mlb_behavioral_disposition.json").read_text())
        self.assertEqual(catalog, set(behavioral["markets"]))
        self.assertEqual(len(catalog), 27)
        allowed = {"KEEP_MEASURED", "WATCH", "FIX", "REBUILD", "UPSTREAM_MODEL_REVIEW", "UNVERIFIED"}
        for market, row in behavioral["markets"].items():
            self.assertIn(row["status"], allowed, market)
            self.assertIn("root_cause", row, market)

    def test_canonical_behavioral_counts_are_stable(self):
        behavioral = json.loads(Path("config/mlb_behavioral_disposition.json").read_text())
        counts = {}
        for row in behavioral["markets"].values():
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        self.assertEqual(
            counts,
            {"KEEP_MEASURED": 7, "WATCH": 1, "FIX": 10, "REBUILD": 8, "UPSTREAM_MODEL_REVIEW": 1},
        )

    def test_validation_registry_contains_all_required_evidence_classes(self):
        validation = json.loads(Path("config/mlb_validation_evidence.json").read_text())
        self.assertEqual(
            validation["required_gates"],
            [
                "historical_point_in_time",
                "untouched_holdout",
                "calibration",
                "settlement_semantics",
                "forward_evidence",
                "production_parity",
            ],
        )

    def test_no_market_is_official_without_complete_validation_realization_and_behavior(self):
        from sportsedge.readiness import audit_readiness

        out = audit_readiness()
        for row in out["markets"]:
            if row["official_bet_enabled"]:
                self.assertTrue(row["validation_complete"], row["market"])
                self.assertTrue(row["feature_contract_complete"], row["market"])
                self.assertTrue(row["feature_realization_complete"], row["market"])
                self.assertTrue(row["behavioral_complete"], row["market"])
                self.assertEqual(row["behavioral_status"], "KEEP_MEASURED", row["market"])
                self.assertTrue(row["frozen_edge_floor"], row["market"])
                self.assertTrue(row["runtime_engine"], row["market"])


if __name__ == "__main__":
    unittest.main()
