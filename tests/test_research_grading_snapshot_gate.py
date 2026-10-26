import unittest
from sportsedge.research_grading_snapshot_gate import audit_grading_snapshots

ENTRY = {"snapshot_id": "entry-1", "captured_at": "2026-10-25T12:00:00-05:00",
         "book": "DK", "event_id": "game-1", "market": "total",
         "offers": {"OVER": -110, "UNDER": -110}}
CLOSE = {**ENTRY, "snapshot_id": "close-2", "captured_at": "2026-10-25T12:04:00-05:00"}
START = "2026-10-25T12:05:00-05:00"


def check(**changes):
    kwargs = {"entry": ENTRY, "close": CLOSE, "selection": "OVER",
              "evaluated_at": "2026-10-25T12:02:30-05:00", "event_start": START}
    kwargs.update(changes)
    return audit_grading_snapshots(**kwargs)


class SnapshotGateTests(unittest.TestCase):
    def test_exact_150_eligible(self):
        self.assertEqual(check()["admission"], "ELIGIBLE_QUOTE")
    def test_151_research_only(self):
        self.assertEqual(check(evaluated_at="2026-10-25T12:02:31-05:00")["admission"], "RESEARCH_AGED_QUOTE")
    def test_at_kickoff_refused(self):
        self.assertEqual(check(evaluated_at="2026-10-25T12:05:00-05:00")["admission"], "REFUSED")
    def test_research_age_never_clv_ready(self):
        result = check(evaluated_at="2026-10-25T12:02:31-05:00")
        self.assertFalse(result["clv_ready"])
        self.assertEqual(result["reason"], "RESEARCH_AGED_QUOTE_NOT_FORWARD_ELIGIBLE")
    def test_300_before_kickoff_research(self):
        self.assertEqual(check(event_start="2026-10-25T12:06:00-05:00", evaluated_at="2026-10-25T12:05:00-05:00")["admission"], "RESEARCH_AGED_QUOTE")
    def test_301_refused(self):
        self.assertEqual(check(event_start="2026-10-25T12:06:00-05:00", evaluated_at="2026-10-25T12:05:01-05:00")["reason"], "ENTRY_OLDER_THAN_300S")
    def test_future_entry_refused(self):
        self.assertEqual(check(entry={**ENTRY, "captured_at": "2026-10-25T12:03:00-05:00"})["reason"], "FUTURE_DATED_ENTRY")
    def test_poststart_refused(self):
        self.assertEqual(check(evaluated_at=START)["admission"], "REFUSED")
    def test_no_close_no_clv(self):
        self.assertFalse(check(close=None)["clv_ready"])
    def test_distinct_close_ready(self):
        self.assertTrue(check()["clv_ready"])
    def test_self_close_refused_for_clv(self):
        self.assertEqual(check(close=ENTRY)["reason"], "SELF_CLOSING_SNAPSHOT")
    def test_cross_book_refused_for_clv(self):
        self.assertEqual(check(close={**CLOSE, "book": "OTHER"})["reason"], "CROSS_SOURCE_OR_MARKET_CLOSE")
    def test_cross_game_refused_for_clv(self):
        self.assertFalse(check(close={**CLOSE, "event_id": "other"})["clv_ready"])
    def test_unpaired_entry_refused(self):
        self.assertEqual(check(entry={**ENTRY, "offers": {"OVER": -110}})["admission"], "REFUSED")
    def test_unpaired_close_no_clv(self):
        self.assertFalse(check(close={**CLOSE, "offers": {"OVER": -110}})["clv_ready"])
    def test_close_at_start_no_clv(self):
        self.assertFalse(check(close={**CLOSE, "captured_at": START})["clv_ready"])
    def test_close_before_entry_no_clv(self):
        self.assertFalse(check(close={**CLOSE, "captured_at": "2026-10-25T11:59:00-05:00"})["clv_ready"])
    def test_malformed_odds_refused(self):
        self.assertEqual(check(entry={**ENTRY, "offers": {"OVER": "NaN", "UNDER": -110}})["admission"], "REFUSED")
    def test_close_sides_mismatch(self):
        self.assertEqual(check(close={**CLOSE, "offers": {"OVER": -110, "DRAW": +150}})["reason"], "CLOSE_OFFER_SIDES_MISMATCH")
    def test_timezone_naive_refused(self):
        self.assertEqual(check(evaluated_at="2026-10-25T12:02:30")["admission"], "REFUSED")
    def test_no_ev_output(self):
        self.assertTrue(set(check()).isdisjoint({"ev", "model_probability", "clv"}))


if __name__ == "__main__":
    unittest.main()
