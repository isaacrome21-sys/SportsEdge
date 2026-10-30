import unittest
from datetime import datetime, timedelta, timezone

from sportsedge.cfb_forward_clv_settlement import select_attested_close

UTC = timezone.utc

class TestCFBForwardCLVSettlement(unittest.TestCase):
    def setUp(self):
        self.first = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)
        self.final = datetime(2026, 9, 19, 22, 0, tzinfo=UTC)
        self.seal = self.final + timedelta(hours=12)
        self.kw = dict(
            first_play_ts=self.first,
            final_status_ts=self.final,
            sealed_at_ts=self.seal,
            timestamp_precision_known=True,
            timestamp_uncertainty_seconds=10,
            source_stable_at_seal=True,
            stabilization_delay_hours=12,
            max_uncertainty_seconds=30,
            safety_margin_seconds=30,
        )

    def candidates(self):
        return [
            {"candidate_id": "early", "quote_ts": self.first - timedelta(minutes=3)},
            {"candidate_id": "late-valid", "quote_ts": self.first - timedelta(seconds=40)},
            {"candidate_id": "inside-margin", "quote_ts": self.first - timedelta(seconds=20)},
            {"candidate_id": "post-start", "quote_ts": self.first + timedelta(seconds=1)},
        ]

    def test_selects_latest_candidate_that_survives_frozen_rule(self):
        out = select_attested_close(self.candidates(), **self.kw)
        self.assertEqual(out["status"], "SELECTED")
        self.assertEqual(out["selected_candidate_id"], "late-valid")
        self.assertFalse(out["promotion_authority"])

    def test_missing_uncertainty_cannot_validate_any_candidate(self):
        kw = dict(self.kw)
        kw["timestamp_uncertainty_seconds"] = None
        out = select_attested_close(self.candidates(), **kw)
        self.assertEqual(out["status"], "CLV_MISSING")
        self.assertIsNone(out["selected_candidate_id"])
        self.assertTrue(all(r["status"] == "INVALID_ATTESTATION_UNVERIFIED" for r in out["candidate_results"]))

    def test_unknown_precision_cannot_validate_any_candidate(self):
        kw = dict(self.kw)
        kw["timestamp_precision_known"] = False
        out = select_attested_close(self.candidates(), **kw)
        self.assertEqual(out["status"], "CLV_MISSING")
        self.assertIsNone(out["selected_candidate_id"])

    def test_unstable_source_cannot_validate_any_candidate(self):
        kw = dict(self.kw)
        kw["source_stable_at_seal"] = False
        out = select_attested_close(self.candidates(), **kw)
        self.assertEqual(out["status"], "CLV_MISSING")

    def test_pre_stabilization_read_remains_pending(self):
        kw = dict(self.kw)
        kw["sealed_at_ts"] = self.final + timedelta(hours=11, minutes=59)
        out = select_attested_close(self.candidates(), **kw)
        self.assertEqual(out["status"], "PENDING_STABILIZATION")
        self.assertIsNone(out["selected_candidate_id"])

    def test_missing_final_status_time_fails_closed(self):
        kw = dict(self.kw)
        kw["final_status_ts"] = None
        out = select_attested_close(self.candidates(), **kw)
        self.assertEqual(out["status"], "CLV_MISSING")

    def test_missing_quote_timestamp_is_not_selected(self):
        candidates = [{"candidate_id": "missing"}] + self.candidates()
        out = select_attested_close(candidates, **self.kw)
        missing = next(r for r in out["candidate_results"] if r["candidate_id"] == "missing")
        self.assertEqual(missing["reason"], "QUOTE_TIMESTAMP_MISSING_OR_INVALID")
        self.assertEqual(out["selected_candidate_id"], "late-valid")

if __name__ == "__main__":
    unittest.main()
