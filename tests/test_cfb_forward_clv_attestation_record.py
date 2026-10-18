import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.cfb_forward_clv_attestation_record import (
    select_attested_close_from_record,
    source_stable_from_record,
)

UTC = timezone.utc


class TestAttestationRecord(unittest.TestCase):
    def setUp(self):
        self.first = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)
        self.final = datetime(2026, 9, 19, 22, 0, tzinfo=UTC)
        self.sealed = self.final + timedelta(hours=12)
        self.hash = "a" * 64
        self.record = {
            "first_play_utc": self.first.isoformat(),
            "final_status_utc": self.final.isoformat(),
            "sealed_at_utc": self.sealed.isoformat(),
            "timestamp_precision_known": True,
            "timestamp_uncertainty_seconds": 10,
            "prior_snapshot_sha256": self.hash,
            "current_snapshot_sha256": self.hash,
            "prior_observed_at_utc": (self.sealed - timedelta(minutes=1)).isoformat(),
            "current_observed_at_utc": self.sealed.isoformat(),
        }

    def candidate(self, seconds_before=120):
        return {"candidate_id": "c1", "quote_ts": self.first - timedelta(seconds=seconds_before)}

    def select(self, record=None):
        return select_attested_close_from_record(
            [self.candidate()],
            attestation_record=record or self.record,
            stabilization_delay_hours=12,
            max_uncertainty_seconds=30,
            safety_margin_seconds=30,
        )

    def test_two_equal_hash_bound_reads_are_stable(self):
        self.assertTrue(source_stable_from_record(self.record))
        self.assertEqual(self.select()["status"], "SELECTED")

    def test_single_read_cannot_claim_stability(self):
        record = dict(self.record)
        record.pop("prior_snapshot_sha256")
        self.assertFalse(source_stable_from_record(record))
        out = self.select(record)
        self.assertEqual(out["status"], "CLV_MISSING")
        self.assertIn("ATTESTATION_SOURCE_UNSTABLE_AT_SEAL", [r["reason"] for r in out["candidate_results"]])

    def test_changed_canonical_snapshot_fails_closed(self):
        record = dict(self.record, current_snapshot_sha256="b" * 64)
        self.assertFalse(source_stable_from_record(record))
        self.assertEqual(self.select(record)["status"], "CLV_MISSING")

    def test_nonincreasing_observation_times_fail_closed(self):
        record = dict(self.record, prior_observed_at_utc=self.sealed.isoformat())
        self.assertFalse(source_stable_from_record(record))
        self.assertEqual(self.select(record)["status"], "CLV_MISSING")

    def test_missing_precision_cannot_validate(self):
        record = dict(self.record, timestamp_precision_known=False)
        out = self.select(record)
        self.assertEqual(out["status"], "CLV_MISSING")
        self.assertIn("TIMESTAMP_PRECISION_UNKNOWN", [r["reason"] for r in out["candidate_results"]])

    def test_unacceptable_uncertainty_cannot_validate(self):
        record = dict(self.record, timestamp_uncertainty_seconds=31)
        self.assertEqual(self.select(record)["status"], "CLV_MISSING")

    def test_stabilization_delay_is_enforced(self):
        record = dict(self.record, sealed_at_utc=(self.final + timedelta(hours=11)).isoformat())
        out = self.select(record)
        self.assertEqual(out["status"], "PENDING_STABILIZATION")

    def test_near_start_quote_is_ambiguous_and_missing(self):
        candidates = [{"candidate_id": "near", "quote_ts": self.first - timedelta(seconds=39)}]
        out = select_attested_close_from_record(
            candidates,
            attestation_record=self.record,
            stabilization_delay_hours=12,
            max_uncertainty_seconds=30,
            safety_margin_seconds=30,
        )
        self.assertEqual(out["status"], "CLV_MISSING")


if __name__ == "__main__":
    unittest.main()
