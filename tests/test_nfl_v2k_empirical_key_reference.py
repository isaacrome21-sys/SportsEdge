import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "sportsedge/sports/nfl/NFL_V2K_EMPIRICAL_KEY_REFERENCE_V1.json"


class NFLV2KEmpiricalKeyReferenceTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(REFERENCE.read_text())

    def test_reference_is_frozen_before_v2k_untouched_readout(self):
        p = self.payload
        self.assertEqual(p["status"], "FROZEN_READY")
        self.assertEqual(p["selected_policy"], "MODERN_REG_2018_2025")
        self.assertEqual(p["reference"]["game_count"], 2127)
        self.assertEqual(p["reference_policy"]["sign_convention"], "OFFICIAL_SCHEDULE_HOME_FINAL_MINUS_AWAY_FINAL")
        self.assertEqual(p["reference_policy"]["overtime_handling"], "OFFICIAL_FINAL_SCORE_INCLUDING_OVERTIME")
        self.assertEqual(p["reference_policy"]["neutral_site_handling"], "INCLUDE_USING_OFFICIAL_SCHEDULE_HOME_AWAY_DESIGNATION")

    def test_required_signed_keys_have_probability_count_and_uncertainty(self):
        p = self.payload
        required = {"-7", "-3", "3", "7"}
        self.assertEqual(set(p["reference"]["signed_margin_mass"]), required)
        self.assertEqual(set(p["reference"]["signed_margin_counts"]), required)
        uncertainty = p["reference"]["uncertainty"]
        for key in required:
            self.assertIn(key, uncertainty)
            self.assertGreater(uncertainty[key]["standard_error"], 0)
            self.assertLess(uncertainty[key]["ci95_low"], p["reference"]["signed_margin_mass"][key])
            self.assertGreater(uncertainty[key]["ci95_high"], p["reference"]["signed_margin_mass"][key])

    def test_reference_is_hash_bound_and_market_blind(self):
        p = self.payload
        self.assertEqual(len(p["reference"]["raw_source_sha256"]), 64)
        self.assertEqual(len(p["reference"]["builder_code_sha256"]), 64)
        self.assertEqual(len(p["reference"]["source_manifest_sha256"]), 64)
        self.assertTrue(p["source_requirements"]["sportsbook_prices_forbidden"])
        self.assertTrue(p["source_requirements"]["v2k_simulations_forbidden"])
        self.assertTrue(p["source_requirements"]["hand_entered_reference_values_forbidden"])

    def test_structural_gate_requires_both_dimensions_and_absolute_key_tolerance(self):
        gate = self.payload["structural_improvement_gate"]
        self.assertTrue(gate["candidate_must_strictly_improve_calibration_slope_metric"])
        self.assertTrue(gate["candidate_must_strictly_improve_signed_key_mass_metric"])
        self.assertFalse(gate["either_dimension_alone_counts_as_pass"])
        self.assertTrue(gate["absolute_per_key_tolerance_still_required"])
        self.assertEqual(self.payload["absolute_mass_tolerance"], 0.005)

    def test_reference_grants_no_betting_authority(self):
        for value in self.payload["authority_boundary"].values():
            self.assertIs(value, False)


if __name__ == "__main__":
    unittest.main()
