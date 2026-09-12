import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.capture_closing_line_archive import (
    ArchiveError,
    build_rows,
    due_events,
    load_policy,
    run,
    window_for,
)

UTC = timezone.utc
NOW = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)
POLICY = load_policy("config/closing_line_archive_policy_v1.json")


def _event(event_id, minutes_out, home="Home", away="Away"):
    return {
        "id": event_id,
        "commence_time": (NOW + timedelta(minutes=minutes_out)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "home_team": home,
        "away_team": away,
    }


def _odds_event(event_id, minutes_out, *, outcomes=2, book="draftkings"):
    base = _event(event_id, minutes_out)
    sides = [{"name": "Home", "price": -110, "point": -3.5}, {"name": "Away", "price": -110, "point": 3.5}]
    base["bookmakers"] = [{"key": book, "last_update": "2026-09-12T15:59:00Z", "markets": [{"key": "spreads", "outcomes": sides[:outcomes]}]}]
    return base


class PolicyTests(unittest.TestCase):
    def test_policy_is_permanently_non_promoting(self):
        self.assertEqual(POLICY["evidence_class"], "NOT_EVIDENCE")
        self.assertFalse(POLICY["promotion_authority"])
        self.assertFalse(POLICY["evidence_clock_authority"])

    def test_policy_id_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"policy_id": "SOMETHING_ELSE"}))
            with self.assertRaises(ArchiveError):
                load_policy(bad)


class WindowTests(unittest.TestCase):
    def test_close_and_decision_windows_resolve(self):
        self.assertEqual(window_for(NOW + timedelta(minutes=10), NOW, POLICY), "close")
        self.assertEqual(window_for(NOW + timedelta(minutes=60), NOW, POLICY), "decision")

    def test_outside_windows_is_not_due(self):
        self.assertIsNone(window_for(NOW + timedelta(minutes=300), NOW, POLICY))
        self.assertIsNone(window_for(NOW + timedelta(minutes=30), NOW, POLICY))

    def test_started_game_is_never_due(self):
        self.assertIsNone(window_for(NOW - timedelta(minutes=1), NOW, POLICY))

    def test_due_events_selects_only_in_window(self):
        events = [_event("a", 10), _event("b", 300), _event("c", 60), _event("d", -5)]
        self.assertEqual(due_events(events, NOW, POLICY), {"a": "close", "c": "decision"})


class RowTests(unittest.TestCase):
    def test_two_sided_market_produces_rows_labelled_not_evidence(self):
        rows, skipped = build_rows("americanfootball_nfl", [_odds_event("a", 10)], {"a": "close"}, NOW, POLICY)
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, [])
        for row in rows:
            self.assertEqual(row["evidence_class"], "NOT_EVIDENCE")
            self.assertEqual(row["window"], "close")
            self.assertNotIn("model_p", row)
            self.assertNotIn("evidence_unit_id", row)

    def test_one_sided_market_is_skipped_not_imputed(self):
        rows, skipped = build_rows("americanfootball_nfl", [_odds_event("a", 10, outcomes=1)], {"a": "close"}, NOW, POLICY)
        self.assertEqual(rows, [])
        self.assertEqual(skipped[0]["reason"], "ONE_SIDED_QUOTE_NOT_IMPUTED")

    def test_unlisted_book_is_ignored(self):
        rows, _ = build_rows("americanfootball_nfl", [_odds_event("a", 10, book="bovada")], {"a": "close"}, NOW, POLICY)
        self.assertEqual(rows, [])

    def test_event_not_due_is_not_captured(self):
        rows, _ = build_rows("americanfootball_nfl", [_odds_event("a", 10)], {}, NOW, POLICY)
        self.assertEqual(rows, [])


class RunTests(unittest.TestCase):
    def _opener(self, index_payload, odds_payload, calls):
        class Resp:
            def __init__(self, obj): self.raw = json.dumps(obj).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return self.raw
        def opener(url, timeout=30):
            if "/events?" in url:
                calls.append("free")
                return Resp(index_payload)
            calls.append("paid")
            return Resp(odds_payload)
        return opener

    def test_no_due_events_makes_no_paid_call(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            report = run(now=NOW, policy=POLICY, out_dir=Path(tmp), keys=["k"], opener=self._opener([_event("a", 400)], [], calls))
        self.assertNotIn("paid", calls)
        self.assertEqual(report["total_rows_written"], 0)

    def test_due_event_writes_append_only_rows(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            report = run(now=NOW, policy=POLICY, out_dir=Path(tmp), keys=["k"], opener=self._opener([_event("a", 10)], [_odds_event("a", 10)], calls))
            self.assertIn("paid", calls)
            self.assertEqual(report["total_rows_written"], 6)
            files = list(Path(tmp).rglob("*.ndjson"))
            self.assertTrue(files)
            first = files[0].read_text().strip().splitlines()
            self.assertTrue(all(json.loads(line)["evidence_class"] == "NOT_EVIDENCE" for line in first))
            before = files[0].read_text()
            run(now=NOW, policy=POLICY, out_dir=Path(tmp), keys=["k"], opener=self._opener([_event("a", 10)], [_odds_event("a", 10)], calls))
            after = files[0].read_text()
            self.assertTrue(after.startswith(before))

    def test_dry_run_never_calls_paid_endpoint(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            run(now=NOW, policy=POLICY, out_dir=Path(tmp), keys=["k"], opener=self._opener([_event("a", 10)], [_odds_event("a", 10)], calls), dry_run=True)
        self.assertNotIn("paid", calls)


if __name__ == "__main__":
    unittest.main()
