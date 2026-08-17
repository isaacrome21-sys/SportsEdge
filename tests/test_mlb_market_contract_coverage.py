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
        feature_markets = set(features["markets"])
        self.assertEqual(catalog, feature_markets)

    def test_every_catalog_market_has_validation_record(self):
        catalog = self._catalog_markets()
        validation = json.loads(Path("config/mlb_validation_evidence.json").read_text())
        validation_markets = set(validation["markets"])
        self.assertEqual(catalog, validation_markets)

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

    def test_no_market_is_official_without_complete_validation(self):
        from sportsedge.readiness import audit_readiness

        out = audit_readiness()
        for row in out["markets"]:
            if row["official_bet_enabled"]:
                self.assertTrue(row["validation_complete"], row["market"])
                self.assertTrue(row["feature_contract_complete"], row["market"])
                self.assertTrue(row["frozen_edge_floor"], row["market"])
                self.assertTrue(row["runtime_engine"], row["market"])


if __name__ == "__main__":
    unittest.main()
