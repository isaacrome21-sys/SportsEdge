import unittest

from scripts.audit_mlb_v8_paired_replay_readiness import audit_rows


def row():
    return {
        "schema": "MLB_V8_ODDSPAPI_PIT_PAIR_V1",
        "source": "ODDSPAPI_HISTORICAL",
        "fixture_id": "123",
        "first_pitch_utc": "2025-07-01T23:10:00+00:00",
        "bookmaker": "DK",
        "market_id": "moneyline",
        "outcome_a_id": "home",
        "outcome_a_name": "Home",
        "outcome_a_decimal": 1.90,
        "outcome_a_quote_utc": "2025-07-01T22:39:50+00:00",
        "outcome_b_id": "away",
        "outcome_b_name": "Away",
        "outcome_b_decimal": 2.00,
        "outcome_b_quote_utc": "2025-07-01T22:39:55+00:00",
        "decision_pair_skew_seconds": 5.0,
        "replay_quote_fresh_180s": True,
        "history_sha256": "a" * 64,
        "close_available": True,
        "close_outcome_a_decimal": 1.85,
        "close_outcome_a_quote_utc": "2025-07-01T23:09:40+00:00",
        "close_outcome_b_decimal": 2.05,
        "close_outcome_b_quote_utc": "2025-07-01T23:09:45+00:00",
        "close_pair_skew_seconds": 5.0,
        "close_after_decision": True,
    }


class MLBV8PairedReplayAuditTests(unittest.TestCase):
    def test_valid_normalized_row_yields_two_selection_pairs_without_promotion_authority(self):
        out = audit_rows([row()])
        self.assertEqual(out["status"], "READY_FOR_REPLAY")
        self.assertEqual(out["valid_pair_count"], 2)
        self.assertEqual(out["rejected_source_row_count"], 0)
        self.assertFalse(out["promotion_authority"])
        self.assertFalse(out["may_change_market_eligibility"])

    def test_missing_close_blocks_entire_audit(self):
        bad = row()
        bad["close_available"] = False
        out = audit_rows([bad])
        self.assertEqual(out["status"], "BLOCKED_PAIRED_MARKET_EVIDENCE")
        self.assertEqual(out["valid_pair_count"], 0)
        self.assertEqual(out["rejected_source_row_count"], 1)
        self.assertIn("CLOSE_MISSING", out["source_row_rejections"][0]["reasons"])

    def test_stale_decision_or_pair_skew_blocks(self):
        bad = row()
        bad["replay_quote_fresh_180s"] = False
        bad["decision_pair_skew_seconds"] = 31
        out = audit_rows([bad])
        reasons = out["source_row_rejections"][0]["reasons"]
        self.assertIn("DECISION_QUOTE_NOT_REPLAY_FRESH", reasons)
        self.assertIn("DECISION_PAIR_SKEW_INVALID", reasons)

    def test_close_at_first_pitch_is_rejected_by_core_temporal_validator(self):
        bad = row()
        bad["close_outcome_a_quote_utc"] = bad["first_pitch_utc"]
        out = audit_rows([bad])
        self.assertEqual(out["status"], "BLOCKED_PAIRED_MARKET_EVIDENCE")
        self.assertEqual(out["invalid_pair_count"], 1)
        self.assertIn("CLOSE_AFTER_START", out["failures"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
