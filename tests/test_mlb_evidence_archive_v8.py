from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.mlb_evidence_archive import (
    EvidenceRow,
    OPEN_CLOSE_ONLY,
    PIT_TIMESTAMPED,
    SOURCE_REGISTRY,
    pair_decision_to_close,
)

NOW = datetime(2026, 9, 3, 20, 0, tzinfo=timezone.utc)
START = NOW + timedelta(hours=2)
SHA = "a" * 64


def row(*, line=7.5, checkpoint="T-90", price=-110, source="SPORTSEDGE_V8_FORWARD", evidence=PIT_TIMESTAMPED):
    return EvidenceRow(
        source_name=source,
        source_uri="https://example.test",
        source_record_sha256=SHA,
        collected_at_utc=NOW.isoformat(),
        observed_at_utc=NOW.isoformat(),
        event_id="123",
        commence_time_utc=START.isoformat(),
        home_team="Home",
        away_team="Away",
        market="totals",
        side="under",
        bookmaker="draftkings",
        american_odds=price,
        line=line,
        participant=None,
        checkpoint=checkpoint,
        evidence_class=evidence,
    )


class EvidenceArchiveV8Tests(unittest.TestCase):
    def test_source_tiers_do_not_promote_open_close_only_to_decision(self):
        self.assertTrue(SOURCE_REGISTRY["THE_ODDS_API"]["decision_eligible"])
        self.assertFalse(SOURCE_REGISTRY["SPORTSGAMEODDS"]["decision_eligible"])
        sgo = row(source="SPORTSGAMEODDS", evidence=OPEN_CLOSE_ONLY)
        self.assertFalse(sgo.decision_eligible)
        self.assertTrue(sgo.close_eligible)

    def test_exact_threshold_close_required(self):
        decision = row(line=7.5, checkpoint="T-90", price=-110)
        moved_close = row(line=8.0, checkpoint="CLOSE_PRESTART", price=-105)
        paired = pair_decision_to_close([decision], [moved_close])
        self.assertEqual(len(paired), 1)
        self.assertFalse(paired[0]["comparable_close"])
        self.assertEqual(paired[0]["reason"], "NO_EXACT_THRESHOLD_CLOSE")

    def test_exact_threshold_close_pairs(self):
        decision = row(line=7.5, checkpoint="T-90", price=-110)
        close = row(line=7.5, checkpoint="CLOSE_PRESTART", price=-102)
        paired = pair_decision_to_close([decision], [close])
        self.assertTrue(paired[0]["comparable_close"])
        self.assertEqual(paired[0]["close_price_same_threshold"], -102)

    def test_pregame_pit_rejects_post_start_observation(self):
        bad = EvidenceRow(**{**row().__dict__, "observed_at_utc": (START + timedelta(seconds=1)).isoformat()})
        with self.assertRaisesRegex(ValueError, "after commence"):
            bad.validate()

    def test_record_carries_eligibility_and_hash(self):
        record = row().as_record()
        self.assertTrue(record["decision_eligible"])
        self.assertTrue(record["close_eligible"])
        self.assertEqual(len(record["row_sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
