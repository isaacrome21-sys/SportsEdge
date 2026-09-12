import unittest

from sportsedge.sports.mlb.paired_replay_readiness import (
    MLBPairedReplayReadinessError,
    validate_decision_close_pair,
)


def quote(*, threshold):
    return {
        "event_id": "game-1",
        "market": "spreads",
        "selection": "home",
        "book": "draftkings",
        "threshold": threshold,
        "observed_at": "2026-06-05T22:30:00+00:00",
        "price": -110,
        "source_sha256": "a" * 64,
        "provenance": "provider_snapshot",
    }


class MLBPairedReplayThresholdBindingTests(unittest.TestCase):
    def test_same_threshold_is_hash_bound(self):
        decision = quote(threshold=-1.5)
        close = quote(threshold=-1.5)
        close["observed_at"] = "2026-06-05T22:50:00+00:00"
        out = validate_decision_close_pair({
            "event_start": "2026-06-05T23:10:00+00:00",
            "decision": decision,
            "close": close,
        })
        self.assertEqual(out["threshold"], "-1.5")
        self.assertEqual(len(out["pair_sha256"]), 64)

    def test_threshold_switch_is_rejected(self):
        decision = quote(threshold=-1.5)
        close = quote(threshold=-2.5)
        close["observed_at"] = "2026-06-05T22:50:00+00:00"
        with self.assertRaisesRegex(MLBPairedReplayReadinessError, "IDENTITY_MISMATCH"):
            validate_decision_close_pair({
                "event_start": "2026-06-05T23:10:00+00:00",
                "decision": decision,
                "close": close,
            })


if __name__ == "__main__":
    unittest.main()
