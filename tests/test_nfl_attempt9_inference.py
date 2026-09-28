from copy import deepcopy
from math import isfinite
import unittest

from sportsedge.sports.nfl.attempt9_inference import (
    EXPECTED_POLICY_GIT_BLOB_SHA1,
    NFLAttempt9InferenceError,
    POLICY_SCHEMA,
    compute_clv_inference,
    load_frozen_inference_policy,
)


class NFLAttempt9InferenceTests(unittest.TestCase):
    def thresholds(self):
        return {
            "minimum_clv_t_stat": 2.0,
            "minimum_distinct_week_clusters": 12,
        }

    def test_frozen_policy_blob_is_bound(self):
        policy = load_frozen_inference_policy()
        self.assertEqual(policy["schema"], POLICY_SCHEMA)
        out = compute_clv_inference(
            [0.01, 0.02],
            [1, 2],
            policy=policy,
            thresholds=self.thresholds(),
        )
        self.assertTrue(out["policy_resolved"])
        self.assertEqual(out["policy_git_blob_sha1"], EXPECTED_POLICY_GIT_BLOB_SHA1)
        self.assertFalse(out["cluster_pass"])

    def test_correlated_week_values_can_pass_iid_but_fail_clustered(self):
        policy = load_frozen_inference_policy()
        values = []
        weeks = []
        for week in range(1, 13):
            value = 0.020 if week <= 6 else -0.005
            values.extend([value] * 20)
            weeks.extend([week] * 20)
        out = compute_clv_inference(
            values,
            weeks,
            policy=policy,
            thresholds=self.thresholds(),
        )
        self.assertGreater(out["iid_t_stat"], 2.0)
        self.assertTrue(out["iid_pass"])
        self.assertEqual(out["cluster_count"], 12)
        self.assertEqual(out["cluster_df"], 11)
        self.assertAlmostEqual(out["cluster_reference_critical"], 2.200985160092, places=12)
        self.assertLess(out["cluster_t_stat"], out["cluster_required_t"])
        self.assertFalse(out["cluster_pass"])
        self.assertFalse(out["combined_pass"])

    def test_both_iid_and_clustered_can_pass(self):
        policy = load_frozen_inference_policy()
        values = []
        weeks = []
        for week in range(1, 13):
            value = 0.010 + week * 0.0005
            values.extend([value] * 10)
            weeks.extend([week] * 10)
        out = compute_clv_inference(
            values,
            weeks,
            policy=policy,
            thresholds=self.thresholds(),
        )
        self.assertTrue(out["iid_pass"])
        self.assertTrue(out["cluster_pass"])
        self.assertTrue(out["combined_pass"])
        self.assertGreaterEqual(out["cluster_t_stat"], out["cluster_required_t"])

    def test_constant_positive_values_do_not_create_infinite_pass(self):
        policy = load_frozen_inference_policy()
        out = compute_clv_inference(
            [0.01] * 12,
            list(range(1, 13)),
            policy=policy,
            thresholds=self.thresholds(),
        )
        self.assertFalse(isfinite(out["iid_t_stat"]))
        self.assertFalse(isfinite(out["cluster_t_stat"]))
        self.assertFalse(out["iid_pass"])
        self.assertFalse(out["cluster_pass"])
        self.assertFalse(out["combined_pass"])

    def test_policy_cannot_relax_frozen_iid_or_cluster_floor(self):
        policy = deepcopy(load_frozen_inference_policy())
        policy["clv_inference"]["cluster_t_stat_floor"] = 1.99
        with self.assertRaisesRegex(NFLAttempt9InferenceError, "CLUSTER_FLOOR_RELAXED"):
            compute_clv_inference(
                [0.01, 0.02],
                [1, 2],
                policy=policy,
                thresholds=self.thresholds(),
            )

    def test_reference_table_fails_closed_outside_frozen_one_season_range(self):
        policy = load_frozen_inference_policy()
        values = [0.010 + week * 0.0001 for week in range(1, 33)]
        weeks = list(range(1, 33))
        with self.assertRaisesRegex(NFLAttempt9InferenceError, "T_REFERENCE_UNSUPPORTED_DF:31"):
            compute_clv_inference(
                values,
                weeks,
                policy=policy,
                thresholds=self.thresholds(),
            )

    def test_policy_numeric_changes_even_if_stricter_are_rejected(self):
        for field, value in (("iid_t_stat_floor", 3.0),
                             ("cluster_t_stat_floor", 3.0),
                             ("minimum_distinct_clusters", 13)):
            policy = deepcopy(load_frozen_inference_policy())
            policy["clv_inference"][field] = value
            with self.assertRaises(NFLAttempt9InferenceError):
                compute_clv_inference([.01,.02], [1,2], policy=policy,
                                      thresholds=self.thresholds())

    def test_cluster_matches_independent_hand_calculation(self):
        from sportsedge.sports.nfl.attempt9_inference import _cluster_t
        t, g = _cluster_t([.02,.04,-.01,.03,.05,.00], [1,1,2,2,3,3])
        mu = .13 / 6
        scores = [.06-2*mu, .02-2*mu, .05-2*mu]
        expected = mu / ((3/2)*sum(x*x for x in scores)/36)**.5
        self.assertEqual(g, 3)
        self.assertAlmostEqual(t, expected, places=12)


if __name__ == "__main__":
    unittest.main()
