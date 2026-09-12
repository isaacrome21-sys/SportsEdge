import copy
import unittest

from sportsedge.sports.mlb.paired_replay_readiness import (
    audit_paired_replay_readiness,
    validate_decision_close_pair,
    MLBPairedReplayReadinessError,
)


def pair():
    base = {
        "event_id": "game-1",
        "market": "MONEYLINE",
        "selection": "HOME",
        "book": "DK",
        "price": -115,
        "source_sha256": "a" * 64,
        "provenance": "provider_historical_snapshot",
    }
    return {
        "event_start": "2025-07-01T23:10:00+00:00",
        "decision": {**base, "observed_at": "2025-07-01T18:00:00+00:00"},
        "close": {**base, "price": -120, "source_sha256": "b" * 64, "observed_at": "2025-07-01T23:05:00+00:00"},
    }


class MLBPairedReplayReadinessTests(unittest.TestCase):
    def test_valid_pair_is_replay_ready_but_never_promotion_authority(self):
        first = audit_paired_replay_readiness([pair()])
        second = audit_paired_replay_readiness([pair()])
        self.assertEqual(first, second)
        self.assertEqual(first["status"], "READY_FOR_REPLAY")
        self.assertEqual(first["valid_pair_count"], 1)
        self.assertFalse(first["promotion_authority"])
        self.assertFalse(first["may_change_market_eligibility"])
        self.assertRegex(first["valid_pairs_sha256"], r"^[0-9a-f]{64}$")

    def test_missing_close_fails_closed(self):
        bad = pair()
        bad["close"] = None
        out = audit_paired_replay_readiness([bad])
        self.assertEqual(out["status"], "BLOCKED_PAIRED_MARKET_EVIDENCE")
        self.assertEqual(out["valid_pair_count"], 0)
        self.assertEqual(out["invalid_pair_count"], 1)

    def test_reconstructed_or_backfilled_quote_is_forbidden(self):
        for provenance in ("reconstructed", "backfilled", "synthetic", "inferred"):
            with self.subTest(provenance=provenance):
                bad = pair()
                bad["decision"]["provenance"] = provenance
                with self.assertRaisesRegex(MLBPairedReplayReadinessError, "PROVENANCE_FORBIDDEN"):
                    validate_decision_close_pair(bad)

    def test_close_must_be_before_start_and_after_decision(self):
        after_start = pair()
        after_start["close"]["observed_at"] = after_start["event_start"]
        with self.assertRaisesRegex(MLBPairedReplayReadinessError, "CLOSE_AFTER_START"):
            validate_decision_close_pair(after_start)

        reversed_order = pair()
        reversed_order["close"]["observed_at"] = "2025-07-01T17:00:00+00:00"
        with self.assertRaisesRegex(MLBPairedReplayReadinessError, "TEMPORAL_ORDER_INVALID"):
            validate_decision_close_pair(reversed_order)

    def test_identity_mismatch_is_rejected(self):
        bad = copy.deepcopy(pair())
        bad["close"]["selection"] = "AWAY"
        with self.assertRaisesRegex(MLBPairedReplayReadinessError, "IDENTITY_MISMATCH"):
            validate_decision_close_pair(bad)


if __name__ == "__main__":
    unittest.main()
