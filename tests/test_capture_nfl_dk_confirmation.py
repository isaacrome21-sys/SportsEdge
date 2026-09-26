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
        run.assert_called_once_with(force=False, as_of=start, write_missed_markers=False)

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
        run.assert_called_once_with(force=False, as_of=late, write_missed_markers=False)

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

    def test_retry_attempt_suppresses_provisional_miss_marker(self):
        start = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        times = iter([start, start, start + timedelta(minutes=1)])
        reports = iter([
            {"status": "MISSED_OR_BLOCKED", "reason": "FETCH_FAILED"},
            {"status": "CAPTURED"},
        ])
        calls = []
        with patch.object(cap, "load_cfg", return_value={"final_minutes_before_kickoff": 30, "final_window_minutes": 15}), \
             patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "next_final_window", return_value=(start, end)), \
             patch.object(cap, "run", side_effect=lambda **kw: (calls.append(kw), next(reports))[1]), \
             patch.object(cap, "final_expected_due_kickoffs", return_value=Counter({"2026-09-27T17:00:00Z": 1})):
            report = cap.run_armed(clock=lambda: next(times), sleeper=lambda _s: None)
        self.assertEqual(report["status"], "CAPTURED")
        self.assertTrue(all(call["write_missed_markers"] is False for call in calls))

    def test_exhausted_window_writes_exactly_one_missed_marker_after_end(self):
        """Every attempt MISSED_OR_BLOCKED → zero markers during window, exactly one after end."""
        start = datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc)
        end = start + timedelta(minutes=15)
        # First tick inside window with remaining <= 60; after sleep, tick at end.
        times = iter([end - timedelta(seconds=30), end])
        marker_calls = []

        def mark_due_missed(*args, **kwargs):
            marker_calls.append((args, kwargs))
            return ["week03/missed/final_after_end.json"]

        with patch.object(cap, "load_cfg", return_value={
                "final_minutes_before_kickoff": 30,
                "final_window_minutes": 15,
                "output_dir": "artifacts/nfl-dk-direct",
            }), \
             patch.object(cap, "load_snapshot", return_value=Snapshot()), \
             patch.object(cap, "next_final_window", return_value=(start, end)), \
             patch.object(cap, "run", return_value={"status": "MISSED_OR_BLOCKED", "reason": "FETCH_FAILED", "detail": "blocked"}), \
             patch.object(cap, "final_expected_due_kickoffs", return_value=Counter({"2026-09-27T17:00:00Z": 1})), \
             patch.object(cap, "mark_due_missed", side_effect=mark_due_missed), \
             patch("sportsedge.nfl_confirmation_schedule.schedule_kickoff_utc", return_value=start + timedelta(minutes=30)):
            report = cap.run_armed(clock=lambda: next(times), sleeper=lambda _s: None)
        self.assertEqual(report["status"], "FINAL_WINDOW_ELAPSED_WITH_INCOMPLETE_CAPTURE")
        self.assertEqual(len(marker_calls), 1)
        self.assertEqual(report["missed_files"], ["week03/missed/final_after_end.json"])

    def test_next_final_window_real_math_horizon_and_captured_exclusion(self):
        class RealSnapshot:
            rows = (
                {"season": "2026", "gameday": "2026-09-27", "gametime": "13:00"},
                {"season": "2026", "gameday": "2026-09-27", "gametime": "13:20"},
            )
        cfg = {
            "timezone": "America/Chicago",
            "week1_tuesday_local_date": "2026-09-08",
            "first_week": 1,
            "final_minutes_before_kickoff": 30,
            "final_window_minutes": 15,
            "output_dir": "unused",
        }
        # nflverse gametime is ET: 13:00 ET = 17:00 UTC, FINAL opens 16:30.
        with patch("sportsedge.nfl_confirmation_schedule.captured_final_kickoffs", return_value=Counter()):
            self.assertIsNone(cap.next_final_window(cfg, datetime(2026, 9, 27, 15, 54, tzinfo=timezone.utc), RealSnapshot()))
            start, end = cap.next_final_window(cfg, datetime(2026, 9, 27, 15, 55, tzinfo=timezone.utc), RealSnapshot())
        self.assertEqual(start, datetime(2026, 9, 27, 16, 30, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 9, 27, 16, 45, tzinfo=timezone.utc))
        with patch("sportsedge.nfl_confirmation_schedule.captured_final_kickoffs", return_value=Counter({"2026-09-27T17:00:00Z": 1})):
            start2, end2 = cap.next_final_window(cfg, datetime(2026, 9, 27, 16, 10, tzinfo=timezone.utc), RealSnapshot())
        self.assertEqual(start2, datetime(2026, 9, 27, 16, 50, tzinfo=timezone.utc))
        self.assertEqual(end2, datetime(2026, 9, 27, 17, 5, tzinfo=timezone.utc))


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
