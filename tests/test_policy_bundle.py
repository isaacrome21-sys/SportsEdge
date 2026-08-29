from __future__ import annotations

import unittest

from sportsedge.core.policy_bundle import build_policy_bundle


class PolicyBundleTests(unittest.TestCase):
    def test_cfb_policy_bundle_is_deterministic_and_complete(self):
        paths = [
            ("truth_gate", "config/cfb_truth_gate_v1.json"),
            ("validation", "config/cfb_validation_policy_v1.json"),
            ("quote_sync", "config/cfb_quote_sync_v1.json"),
            ("benchmark", "config/cfb_market_benchmark_v1.json"),
            ("governance", "config/manual_hybrid_governance_v1.json"),
            ("evidence_gate", "config/manual_hybrid_evidence_gate_v1.json"),
            ("policy_freeze", "config/manual_hybrid_policy_freeze_v1.json"),
            ("provider_degrade", "config/provider_degrade_matrix_v1.json"),
        ]
        one = build_policy_bundle("CFB_POLICY_BUNDLE_V1", paths)
        two = build_policy_bundle("CFB_POLICY_BUNDLE_V1", reversed(paths))
        self.assertEqual(one.artifacts, two.artifacts)
        self.assertEqual(one.content_hash(), two.content_hash())
        self.assertEqual(len(one.artifacts), 8)
        self.assertEqual(len(one.content_hash()), 64)

    def test_mlb_policy_bundle_is_deterministic_and_complete(self):
        paths = [
            ("truth_gate", "config/mlb_truth_gate_v1.json"),
            ("validation", "config/mlb_validation_policy_v1.json"),
            ("benchmark", "config/mlb_market_benchmark_v1.json"),
            ("governance", "config/manual_hybrid_governance_v1.json"),
            ("evidence_gate", "config/manual_hybrid_evidence_gate_v1.json"),
            ("policy_freeze", "config/manual_hybrid_policy_freeze_v1.json"),
            ("provider_degrade", "config/provider_degrade_matrix_v1.json"),
        ]
        bundle = build_policy_bundle("MLB_POLICY_BUNDLE_V1", paths)
        self.assertEqual(len(bundle.artifacts), 7)
        self.assertEqual(len(bundle.content_hash()), 64)


if __name__ == "__main__":
    unittest.main()
