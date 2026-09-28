import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
POLICY = json.loads((ROOT / "config/nfl_attempt9_prospective_inference_v1.json").read_text())
GOV = json.loads((ROOT / "config/nfl_2026_prospective_governance_v1.json").read_text())


class NFLAttempt9InferencePolicyTests(unittest.TestCase):
    def test_addendum_only_hardens_existing_t_stat_gate(self):
        frozen = GOV["nfl_game_market_precommitted_thresholds"]
        inference = POLICY["clv_inference"]
        self.assertEqual(inference["iid_t_stat_floor"], frozen["minimum_clv_t_stat"])
        self.assertGreaterEqual(inference["cluster_t_stat_floor"], frozen["minimum_clv_t_stat"])
        self.assertGreaterEqual(
            inference["minimum_distinct_clusters"],
            frozen["minimum_distinct_week_clusters"],
        )
        self.assertFalse(POLICY["governance"]["may_lower_existing_thresholds"])

    def test_week_cluster_method_and_small_sample_reference_are_frozen(self):
        inference = POLICY["clv_inference"]
        self.assertEqual(inference["cluster_estimator"], "CR1_INTERCEPT_ONLY_CLUSTER_ROBUST")
        self.assertEqual(inference["cluster_unit"], "NFL_WEEK")
        self.assertEqual(inference["cluster_df"], "G_MINUS_1")
        self.assertEqual(inference["cluster_reference_distribution"], "STUDENT_T")
        self.assertEqual(inference["cluster_reference_quantile"], 0.975)
        self.assertIn("MAX_2_0", inference["cluster_pass_rule"])
        self.assertIn("IID_T_STAT", inference["combined_pass_rule"])

    def test_one_game_market_selection_can_contribute_only_once(self):
        uniqueness = POLICY["decision_uniqueness"]
        self.assertEqual(uniqueness["key"], ["game_id", "market", "selection"])
        self.assertEqual(
            uniqueness["canonical_rule"],
            "EARLIEST_VALID_DECISION_AT_UTC_THEN_SHA256",
        )
        self.assertFalse(uniqueness["later_captures_may_increase_sample_size"])
        self.assertFalse(uniqueness["evidence_availability_may_choose_capture"])
        self.assertFalse(uniqueness["backfill_allowed"])

    def test_addendum_grants_no_authority(self):
        authority = POLICY["governance"]
        for key in ("promotion_authority", "official_authority", "staking_authority"):
            self.assertFalse(authority[key])
        self.assertFalse(authority["may_change_model_probability"])
        self.assertFalse(authority["may_change_model_features"])
        self.assertFalse(authority["may_change_edge_floor"])


if __name__ == "__main__":
    unittest.main()
