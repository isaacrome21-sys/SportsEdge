#!/usr/bin/env python3
from __future__ import annotations

import json
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.error import HTTPError

import scripts.capture_nfl_dk_confirmation as cap
from sportsedge.draftkings_game_market_source import RawDraftKingsBoard
from sportsedge.nfl_direct_capture_source import game_rows_direct


class Snapshot:
    def provenance(self):
        return {
            "source": "fixture",
            "sha256": "schedule-sha",
            "matching_semantics": "KICKOFF_UTC_MULTIPLICITY",
        }


def fixture_board() -> RawDraftKingsBoard:
    payload = {
        "events": [
            {
                "id": "1",
                "name": "ATL Falcons @ GB Packers",
                "startEventDate": "2026-09-25T00:15:00Z",
            }
        ],
        "markets": [
            {"id": "m1", "eventId": "1", "name": "Spread"},
            {"id": "m2", "eventId": "1", "name": "Total"},
        ],
        "selections": [
            {"marketId": "m1", "label": "ATL Falcons +6.5", "points": 6.5, "displayOdds": {"american": "+110"}},
            {"marketId": "m1", "label": "GB Packers -6.5", "points": -6.5, "displayOdds": {"american": "-130"}},
            {"marketId": "m2", "label": "Over 44.5", "points": 44.5, "displayOdds": {"american": "-110"}},
            {"marketId": "m2", "label": "Under 44.5", "points": 44.5, "displayOdds": {"american": "-110"}},
        ],
    }
    raw = json.dumps(payload).encode()
    return RawDraftKingsBoard(
        "americanfootball_nfl",
        "fixture",
        raw,
        datetime(2026, 9, 23, tzinfo=timezone.utc),
        payload,
    )


class DirectAdmissionTests(unittest.TestCase):
    def test_spread_sign_is_preserved_in_game_level_record(self):
        board = fixture_board()
        rows = game_rows_direct(
            cap.board_transport(board),
            week_of=lambda _dt: 3,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["spread"]["status"], "OK")
        self.assertEqual(rows[0]["spread"]["away_point"], 6.5)
        self.assertEqual(rows[0]["spread"]["home_point"], -6.5)
        self.assertEqual(rows[0]["total"]["status"], "OK")
        self.assertEqual(rows[0]["total"]["point"], 44.5)

    def test_record_matches_confirmation_validator_shape(self):
        board = fixture_board()
        games = game_rows_direct(cap.board_transport(board), week_of=lambda _dt: 3)
        expected = Counter({"2026-09-25T00:15:00Z": 1})
        record = cap.build_record(
            kind="FINAL",
            week=3,
            now=datetime(2026, 9, 25, 0, 45, tzinfo=timezone.utc),
            board=board,
            date_header="Wed, 23 Sep 2026 00:00:00 GMT",
            raw_rel="raw/draftkings-direct/fixture.json",
            raw_sha="abc123",
            snapshot=Snapshot(),
            expected=expected,
            games=games,
        )
        self.assertEqual(record["capture_kind"], "FINAL")
        self.assertEqual(record["book"], "draftkings")
        self.assertEqual(record["source_class"], "DRAFTKINGS_DIRECT_WEB_V1")
        self.assertTrue(record["retrieved_at_utc"])
        self.assertTrue(record["hashes"])
        self.assertEqual(record["schedule"]["matching_semantics"], "KICKOFF_UTC_MULTIPLICITY")
        self.assertEqual(record["games"][0]["spread"]["status"], "OK")
        self.assertEqual(record["games"][0]["total"]["status"], "OK")


class WindowSemanticsTests(unittest.TestCase):
    def test_no_window_does_not_touch_draftkings(self):
        with patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "determine_due", return_value=(None, Counter())), \
             patch.object(cap, "fetch_once") as fetch:
            report = cap.run(force=False, as_of=datetime(2026, 9, 23, 12, tzinfo=timezone.utc))
        self.assertEqual(report["status"], "NO_WINDOW")
        fetch.assert_not_called()

    def test_off_window_proof_failure_writes_no_missed_marker(self):
        with patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "determine_due", return_value=(None, Counter())), \
             patch.object(cap, "fetch_once", side_effect=cap.Blocked("HTTP_ERROR", "status=403")), \
             patch.object(cap, "mark_due_missed") as mark:
            report = cap.run(force=True, as_of=datetime(2026, 9, 23, 12, tzinfo=timezone.utc))
        self.assertEqual(report["status"], "PROOF_BLOCKED")
        mark.assert_not_called()

    def test_due_window_fetch_failure_records_missed_marker(self):
        expected = Counter({"2026-09-25T00:15:00Z": 1})
        opener = {"week": 3, "target": datetime(2026, 9, 22, 14, tzinfo=timezone.utc), "expected": expected, "path": "unused"}
        with patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "determine_due", return_value=(opener, Counter())), \
             patch.object(cap, "fetch_once", side_effect=cap.Blocked("HTTP_ERROR", "status=403")), \
             patch.object(cap, "mark_due_missed", return_value=["missed.json"]) as mark:
            report = cap.run(force=False, as_of=datetime(2026, 9, 22, 14, 15, tzinfo=timezone.utc))
        self.assertEqual(report["status"], "MISSED_OR_BLOCKED")
        self.assertEqual(report["missed_files"], ["missed.json"])
        mark.assert_called_once()


class ArmedWindowTests(unittest.TestCase):
    def test_armed_waits_until_window_start_then_captures(self):
        start = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        ticks = iter([start - timedelta(minutes=20), start])
        sleeps = []
        with patch.object(cap, "load_cfg", return_value={"final_minutes_before_kickoff": 30, "final_window_minutes": 15}), \
             patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "next_final_window", return_value=(start, end)), \
             patch.object(cap, "run", return_value={"status": "CAPTURED"}) as run:
            report = cap.run_armed(clock=lambda: next(ticks), sleeper=sleeps.append)
        self.assertEqual(report["status"], "CAPTURED")
        self.assertEqual(sleeps, [1200.0])
        run.assert_called_once_with(force=False, as_of=start)

    def test_armed_never_calls_capture_after_window_end(self):
        start = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        with patch.object(cap, "load_cfg", return_value={"final_minutes_before_kickoff": 30, "final_window_minutes": 15}), \
             patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "next_final_window", return_value=(start, end)), \
             patch.object(cap, "run") as run:
            report = cap.run_armed(clock=lambda: end, sleeper=lambda _s: None)
        self.assertEqual(report["status"], "FINAL_WINDOW_ELAPSED_WITH_INCOMPLETE_CAPTURE")
        run.assert_not_called()

    def test_late_trigger_inside_window_captures_immediately(self):
        start = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        late = start + timedelta(minutes=10)
        with patch.object(cap, "load_cfg", return_value={"final_minutes_before_kickoff": 30, "final_window_minutes": 15}), \
             patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "next_final_window", return_value=(start, end)), \
             patch.object(cap, "run", return_value={"status": "CAPTURED"}) as run:
            report = cap.run_armed(clock=lambda: late, sleeper=lambda _s: self.fail("must not sleep before capture"))
        self.assertEqual(report["status"], "CAPTURED")
        run.assert_called_once_with(force=False, as_of=late)

    def test_duplicate_run_exits_when_first_writer_already_captured(self):
        start = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        times = iter([start, start])
        with patch.object(cap, "load_cfg", return_value={"final_minutes_before_kickoff": 30, "final_window_minutes": 15}), \
             patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "next_final_window", return_value=(start, end)), \
             patch.object(cap, "run", return_value={"status": "MISSED_OR_BLOCKED"}), \
             patch.object(cap, "final_expected_due_kickoffs", return_value=Counter()):
            report = cap.run_armed(clock=lambda: next(times), sleeper=lambda _s: None)
        self.assertEqual(report["status"], "ALREADY_CAPTURED")


class FetchBlockedTests(unittest.TestCase):
    def test_403_is_blocked_with_detail(self):
        def boom(*_a, **_k):
            raise HTTPError("https://x", 403, "Forbidden", hdrs=None, fp=None)

        with patch("scripts.capture_nfl_dk_confirmation.urlopen", side_effect=boom):
            with self.assertRaises(cap.Blocked) as ctx:
                cap.fetch_once()
        self.assertEqual(ctx.exception.reason, "HTTP_ERROR")
        self.assertIn("status=403", ctx.exception.detail)
        self.assertIn("Forbidden", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
