import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.mlb_acceptance_matrix import MLBAcceptanceMatrixError, build_acceptance_matrix


class MLBAcceptanceMatrixTests(unittest.TestCase):
    @staticmethod
    def _catalog_markets():
        raw = json.loads(Path("config/mlb_market_catalog.json").read_text())
        markets = set()
        for key, rows in raw.items():
            if key == "schema_version" or not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, str):
                    markets.add(row)
                elif isinstance(row, dict) and row.get("market"):
                    markets.add(str(row["market"]))
        return markets

    def test_every_catalog_market_has_one_acceptance_family(self):
        out = build_acceptance_matrix()
        catalog = self._catalog_markets()
        markets = [row["market"] for row in out["markets"]]
        self.assertEqual(out["market_count"], len(catalog))
        self.assertEqual(set(markets), catalog)
        self.assertEqual(len(markets), len(set(markets)))
        self.assertTrue(all(row["acceptance_family"] for row in out["markets"]))

    def test_every_market_has_structural_settlement_and_six_evidence_requirements(self):
        out = build_acceptance_matrix()
        expected_gates = {
            "historical_point_in_time",
            "untouched_holdout",
            "calibration",
            "settlement_semantics",
            "forward_evidence",
            "production_parity",
        }
        for row in out["markets"]:
            req = row["requirements"]
            self.assertTrue(req["runtime_contract"], row["market"])
            self.assertTrue(req["structural_behavior"], row["market"])
            self.assertTrue(req["settlement_semantics"], row["market"])
            self.assertEqual(set(req["evidence_gates"]), expected_gates, row["market"])

    def test_current_runtime_presence_does_not_equal_acceptance(self):
        out = build_acceptance_matrix()
        rows = {row["market"]: row for row in out["markets"]}
        for market in ("RUNS", "STOLEN_BASES", "PITCHER_K", "PITCHER_HITS_ALLOWED"):
            row = rows[market]
            self.assertTrue(row["current_state"]["runtime_engine"], market)
            self.assertEqual(row["current_state"]["behavioral_status"], "KEEP_MEASURED", market)
            self.assertFalse(row["acceptance_complete"], market)

    def test_home_runs_is_separate_measured_incumbent_family(self):
        out = build_acceptance_matrix()
        rows = {row["market"]: row for row in out["markets"]}
        hr = rows["HOME_RUNS"]
        self.assertEqual(hr["acceptance_family"], "HOME_RUN_GENERIC_INCUMBENT")
        self.assertEqual(hr["current_state"]["behavioral_status"], "KEEP_MEASURED")
        self.assertIn("GENERIC_MEASURED_BASELINE_ACTIVE", str(hr["current_state"]["remediation_state"]))

    def test_known_structural_rebuilds_keep_their_required_substrate(self):
        out = build_acceptance_matrix()
        rows = {row["market"]: row for row in out["markets"]}
        for market in ("F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS"):
            checks = set(rows[market]["requirements"]["structural_behavior"])
            self.assertIn("REAL_INNING_STATE_SUBSTRATE", checks)
            self.assertIn("NO_FULL_GAME_SCALING_SHORTCUT", checks)
        self.assertIn(
            "ORDERING_AWARE_PLATE_APPEARANCE_SIMULATION",
            rows["FIRST_HOME_RUN"]["requirements"]["structural_behavior"],
        )
        self.assertIn(
            "NO_ROLLING_WIN_RATE_PROXY",
            rows["PITCHER_RECORD_WIN"]["requirements"]["structural_behavior"],
        )

    def test_new_unmeasured_markets_cannot_be_complete_by_architecture_alone(self):
        out = build_acceptance_matrix()
        unmeasured = {
            row["market"]
            for row in out["markets"]
            if row["current_state"]["behavioral_status"] == "UNMEASURED"
        }
        behavioral = json.loads(Path("config/mlb_behavioral_disposition.json").read_text())
        expected_unmeasured = {
            market for market, row in behavioral["markets"].items()
            if row["status"] == "UNMEASURED"
        }
        self.assertEqual(unmeasured, expected_unmeasured)
        by_market = {row["market"]: row for row in out["markets"]}
        self.assertTrue(all(not by_market[market]["acceptance_complete"] for market in unmeasured))

    def test_matrix_fails_if_a_catalog_market_is_unassigned(self):
        raw = json.loads(Path("config/mlb_acceptance_matrix.json").read_text())
        raw["families"]["HITTER_JOINT"]["markets"].remove("HITS")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "matrix.json"
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(MLBAcceptanceMatrixError, "coverage mismatch"):
                build_acceptance_matrix(matrix_path=path)

    def test_matrix_fails_if_market_is_assigned_twice(self):
        raw = json.loads(Path("config/mlb_acceptance_matrix.json").read_text())
        raw["families"]["HOME_RUN_GENERIC_INCUMBENT"]["markets"].append("HITS")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "matrix.json"
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(MLBAcceptanceMatrixError, "multiple acceptance families"):
                build_acceptance_matrix(matrix_path=path)

    def test_policy_forbids_synthetic_or_ci_waiver_as_evidence(self):
        out = build_acceptance_matrix()
        self.assertFalse(out["policy"]["synthetic_structural_tests_count_as_historical_evidence"])
        self.assertFalse(out["policy"]["ci_waiver_counts_as_validation_evidence"])
        self.assertFalse(out["policy"]["behavioral_evidence_inherits_across_engine_changes"])


if __name__ == "__main__":
    unittest.main()
