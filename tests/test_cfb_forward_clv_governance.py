import math
import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.cfb_forward_clv_governance import (
    classify_cluster_regime,
    deterministic_bootstrap_seed,
    evaluate_first_play_attestation,
    evaluate_promotion_inference,
    wild_cluster_bootstrap_t,
)

UTC = timezone.utc

class TestFirstPlayAttestation(unittest.TestCase):
    def setUp(self):
        self.final = datetime(2026, 9, 19, 22, 0, tzinfo=UTC)
        self.first = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)
        self.seal = self.final + timedelta(hours=12)

    def evaluate(self, quote, **overrides):
        args = dict(quote_ts=quote, first_play_ts=self.first, final_status_ts=self.final,
            sealed_at_ts=self.seal, timestamp_precision_known=True,
            timestamp_uncertainty_seconds=10, source_stable_at_seal=True)
        args.update(overrides)
        return evaluate_first_play_attestation(**args)

    def test_blocks_before_12h_stabilization(self):
        out = self.evaluate(self.first-timedelta(minutes=2), sealed_at_ts=self.final+timedelta(hours=11,minutes=59))
        self.assertEqual(out.status, "PENDING_STABILIZATION")

    def test_blocks_missing_final_status_timestamp(self):
        out = self.evaluate(self.first-timedelta(minutes=2), final_status_ts=None)
        self.assertEqual(out.reason, "FINAL_STATUS_TIMESTAMP_MISSING")

    def test_blocks_missing_precision(self):
        out = self.evaluate(self.first-timedelta(minutes=2), timestamp_precision_known=False)
        self.assertEqual(out.status, "INVALID_ATTESTATION_UNVERIFIED")
        self.assertEqual(out.reason, "TIMESTAMP_PRECISION_UNKNOWN")

    def test_blocks_missing_uncertainty(self):
        out = self.evaluate(self.first-timedelta(minutes=2), timestamp_uncertainty_seconds=None)
        self.assertEqual(out.reason, "TIMESTAMP_UNCERTAINTY_MISSING")

    def test_blocks_uncertainty_over_30_seconds(self):
        out = self.evaluate(self.first-timedelta(minutes=2), timestamp_uncertainty_seconds=31)
        self.assertEqual(out.reason, "TIMESTAMP_UNCERTAINTY_EXCEEDS_MAX")

    def test_blocks_unstable_source_at_seal(self):
        out = self.evaluate(self.first-timedelta(minutes=2), source_stable_at_seal=False)
        self.assertEqual(out.reason, "ATTESTATION_SOURCE_UNSTABLE_AT_SEAL")

    def test_blocks_inside_uncertainty_plus_safety_margin(self):
        out = self.evaluate(self.first-timedelta(seconds=39), timestamp_uncertainty_seconds=10)
        self.assertEqual(out.reason, "QUOTE_INSIDE_UNCERTAINTY_SAFETY_MARGIN")
        self.assertEqual(out.required_margin_seconds, 40)

    def test_exact_margin_is_valid(self):
        out = self.evaluate(self.first-timedelta(seconds=40), timestamp_uncertainty_seconds=10)
        self.assertEqual(out.status, "VALID_ATTESTED_PRE_START")

    def test_post_start_is_never_valid(self):
        out = self.evaluate(self.first)
        self.assertEqual(out.status, "INVALID_POST_START")

class TestClusterRegime(unittest.TestCase):
    def test_regular_season_explicitly_allowed(self):
        self.assertEqual(classify_cluster_regime(season_type="regular season"), "FBS_REGULAR_SEASON_ONLY")
    def test_bowl_is_diagnostic_only(self):
        self.assertEqual(classify_cluster_regime(season_type="postseason", notes="Rose Bowl"), "POSTSEASON_DIAGNOSTIC_ONLY")
    def test_unknown_regime_fails_closed(self):
        self.assertEqual(classify_cluster_regime(), "REGIME_UNVERIFIED_BLOCKED")

class TestWildClusterBootstrap(unittest.TestCase):
    def test_seed_is_deterministic_and_market_bound(self):
        a=deterministic_bootstrap_seed(policy_sha256="abc",market_ledger="CFB_SPREAD")
        b=deterministic_bootstrap_seed(policy_sha256="abc",market_ledger="CFB_SPREAD")
        c=deterministic_bootstrap_seed(policy_sha256="abc",market_ledger="CFB_TOTAL")
        self.assertEqual(a,b); self.assertNotEqual(a,c)
    def test_bootstrap_is_deterministic(self):
        clusters={f"2026-09-{i:02d}":0.5+i/10 for i in range(1,13)}
        a=wild_cluster_bootstrap_t(clusters,policy_sha256="abc",market_ledger="CFB_SPREAD",repetitions=199)
        b=wild_cluster_bootstrap_t(clusters,policy_sha256="abc",market_ledger="CFB_SPREAD",repetitions=199)
        self.assertEqual(a,b); self.assertEqual(a["clusters"],12); self.assertTrue(0<a["two_sided_p"]<=1)
    def test_postseason_rows_cannot_supply_cluster_floor(self):
        rows=[{"season_type":"regular season","slate_date_ct":f"2026-09-{i:02d}","clv_pp":2.0} for i in range(1,12)]
        rows.append({"season_type":"postseason","regime_note":"conference championship","slate_date_ct":"2026-12-05","clv_pp":20.0})
        out=evaluate_promotion_inference(rows,policy_sha256="abc",market_ledger="CFB_SPREAD",repetitions=99)
        self.assertFalse(out["inference_gate_pass"]); self.assertEqual(out["eligible_regular_season_clusters"],11)
        self.assertIn("MINIMUM_REGULAR_SEASON_SLATE_CLUSTERS_NOT_MET",out["blockers"])
    def test_bootstrap_cannot_rescue_failed_mean(self):
        rows=[{"season_type":"regular season","slate_date_ct":f"2026-09-{i:02d}","clv_pp":0.1} for i in range(1,13)]
        out=evaluate_promotion_inference(rows,policy_sha256="abc",market_ledger="CFB_TOTAL",repetitions=99)
        self.assertFalse(out["inference_gate_pass"]); self.assertIn("MEAN_CLV_GATE_FAILED",out["blockers"]); self.assertIsNone(out["bootstrap_two_sided_p"])

if __name__ == "__main__":
    unittest.main()
