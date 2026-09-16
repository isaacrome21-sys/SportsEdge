from pathlib import Path
import unittest

from sportsedge.mlb_moneyline_forward_lane import (
    MLBMoneylineForwardLaneError,
    load_forward_lane_binding,
    require_record_binding,
)


class MLBMoneylineForwardLaneTest(unittest.TestCase):
    def test_active_v2_lane_is_frozen_and_non_authoritative(self):
        binding = load_forward_lane_binding()
        self.assertEqual(binding["lane_id"], "MLB_MONEYLINE_DK_T30_V1")
        self.assertEqual(binding["policy_id"], "PROMOTION_EVIDENCE_POLICY_V2")
        self.assertEqual(binding["evidence_ref"], "refs/heads/main")
        self.assertEqual(binding["edge_floor_probability_points"], 0.03)
        self.assertIs(binding["promotion_authority"], False)
        for field in (
            "lane_definition_sha256",
            "market_definition_sha256",
            "policy_sha256",
            "policy_manifest_sha256",
            "edge_floor_config_sha256",
        ):
            self.assertEqual(len(binding[field]), 64)

    def test_record_binding_requires_exact_frozen_identities(self):
        binding = load_forward_lane_binding()
        row = dict(binding)
        require_record_binding(row, binding)
        row["policy_sha256"] = "0" * 64
        with self.assertRaisesRegex(MLBMoneylineForwardLaneError, "policy_sha256"):
            require_record_binding(row, binding)

    def test_lane_config_exists_before_judged_stream(self):
        self.assertTrue(Path("config/mlb_moneyline_forward_lane_v1.json").is_file())


if __name__ == "__main__":
    unittest.main()
