import copy
import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.cfb_forward_clv_runtime import CFBForwardRuntimeError, settle_close_group

UTC = timezone.utc


class TestCFBForwardCLVRuntime(unittest.TestCase):
    def setUp(self):
        self.first = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)
        self.final = datetime(2026, 9, 19, 22, 0, tzinfo=UTC)
        self.sealed = self.final + timedelta(hours=12)
        self.policy = {
            "policy_id": "CFB_FORWARD_CLV_POLICY_V1",
            "version": "1.0.3",
            "status": "FROZEN",
            "capture_schedule": {"close": {"actual_start_attestation": {
                "stabilization_delay_hours": 12,
                "max_acceptable_timestamp_uncertainty_seconds": 30,
                "safety_margin_seconds": 30,
            }}},
        }
        h = "a" * 64
        self.attestation = {
            "espn_event_id": "401234567",
            "first_play_utc": self.first.isoformat(),
            "final_status_utc": self.final.isoformat(),
            "sealed_at_utc": self.sealed.isoformat(),
            "timestamp_precision_known": True,
            "timestamp_uncertainty_seconds": 10,
            "prior_snapshot_sha256": h,
            "current_snapshot_sha256": h,
            "prior_observed_at_utc": (self.sealed - timedelta(minutes=1)).isoformat(),
            "current_observed_at_utc": self.sealed.isoformat(),
        }

    def raw(self, seconds_before):
        return {
            "policy_id": "CFB_FORWARD_CLV_POLICY_V1",
            "policy_version": "1.0.3",
            "espn_event_id": "401234567",
            "captured_at_utc": (self.first - timedelta(seconds=seconds_before)).isoformat(),
            "capture_kind": "CLOSE_RAW_SNAPSHOT",
        }

    def test_selects_latest_only_after_hash_bound_attestation(self):
        out = settle_close_group(
            [self.raw(180), self.raw(40), self.raw(20)],
            attestation_record=self.attestation,
            policy=self.policy,
        )
        self.assertEqual(out["status"], "SELECTED")
        self.assertFalse(out["promotion_authority"])
        self.assertEqual(out["raw_snapshot_count"], 3)
        valid = [r for r in out["candidate_results"] if r["status"] == "VALID_ATTESTED_PRE_START"]
        self.assertEqual(len(valid), 2)

    def test_unstable_attestation_cannot_fall_back_to_quote_before_first_play(self):
        att = dict(self.attestation, current_snapshot_sha256="b" * 64)
        out = settle_close_group([self.raw(180)], attestation_record=att, policy=self.policy)
        self.assertEqual(out["status"], "CLV_MISSING")
        self.assertIsNone(out["selected_candidate_id"])
        self.assertIn("ATTESTATION_SOURCE_UNSTABLE_AT_SEAL", [r["reason"] for r in out["candidate_results"]])

    def test_pre_stabilization_attestation_remains_pending(self):
        att = dict(self.attestation, sealed_at_utc=(self.final + timedelta(hours=11)).isoformat())
        out = settle_close_group([self.raw(180)], attestation_record=att, policy=self.policy)
        self.assertEqual(out["status"], "PENDING_STABILIZATION")

    def test_event_identity_mismatch_hard_blocks(self):
        att = dict(self.attestation, espn_event_id="different")
        with self.assertRaisesRegex(CFBForwardRuntimeError, "ATTESTATION_EVENT_ID_MISMATCH"):
            settle_close_group([self.raw(180)], attestation_record=att, policy=self.policy)

    def test_raw_policy_identity_mismatch_hard_blocks(self):
        raw = self.raw(180)
        raw["policy_version"] = "1.0.2"
        with self.assertRaisesRegex(CFBForwardRuntimeError, "RAW_CLOSE_POLICY_IDENTITY_MISMATCH"):
            settle_close_group([raw], attestation_record=self.attestation, policy=self.policy)

    def test_policy_constants_cannot_drift_silently(self):
        policy = copy.deepcopy(self.policy)
        policy["capture_schedule"]["close"]["actual_start_attestation"]["safety_margin_seconds"] = 0
        with self.assertRaisesRegex(CFBForwardRuntimeError, "CFB_FORWARD_ATTESTATION_POLICY_UNEXPECTED"):
            settle_close_group([self.raw(180)], attestation_record=self.attestation, policy=policy)

    def test_no_raw_snapshots_retains_missing_close(self):
        out = settle_close_group([], attestation_record=self.attestation, policy=self.policy)
        self.assertEqual(out["status"], "CLV_MISSING")
        self.assertEqual(out["raw_snapshot_count"], 0)


if __name__ == "__main__":
    unittest.main()
