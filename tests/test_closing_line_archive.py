import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.capture_closing_line_archive import (
    ArchiveError,
    START_GUARD_FAILURE_MODES,
    START_GUARD_SCHEDULED,
    build_rows,
    due_events,
    load_policy,
    run,
    window_for,
    windows_for,
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
    base["bookmakers"] = [
        {
            "key": book,
            "last_update": "2026-09-12T15:59:00Z",
            "markets": [{"key": "spreads", "outcomes": sides[:outcomes]}],
        }
    ]
    return base


class PolicyTests(unittest.TestCase):
    def test_policy_is_permanently_non_promoting(self):
        self.assertEqual(POLICY["evidence_class"], "NOT_EVIDENCE")
        self.assertFalse(POLICY["promotion_authority"])
        self.assertFalse(POLICY["evidence_clock_authority"])

    def test_paid_archive_is_draftkings_only_us_and_excludes_pinnacle_fanduel(self):
        self.assertEqual(POLICY["regions"], "us")
        self.assertEqual(POLICY["books"], ["draftkings"])
        self.assertNotIn("fanduel", POLICY["books"])
        self.assertNotIn("pinnacle", POLICY["books"])
        self.assertNotIn("eu", {part.strip() for part in POLICY["regions"].split(",")})
        self.assertEqual(POLICY["market_radar"]["market_maker_books"], [])

    def test_t0_prestart_is_all_sports_and_non_promoting(self):
        self.assertEqual(set(POLICY["sports"]), {"NFL", "CFB", "UFC"})
        self.assertNotIn("MLB", POLICY["sports"])
        self.assertFalse(POLICY["parked_sports"]["MLB"]["scheduled_paid_capture"])
        self.assertEqual(POLICY["sports"]["UFC"], "mma_mixed_martial_arts")
        self.assertEqual(POLICY["windows"]["t0_prestart"], {
            "min_minutes_before_start": 0,
            "max_minutes_before_start": 5,
        })
        self.assertTrue(POLICY["integrity"]["must_be_before_start"])
        self.assertFalse(POLICY["promotion_authority"])

    def test_policy_id_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps({"policy_id": "SOMETHING_ELSE"}))
            with self.assertRaises(ArchiveError):
                load_policy(bad)


class WindowTests(unittest.TestCase):
    def test_t0_close_and_decision_windows_resolve(self):
        self.assertEqual(window_for(NOW + timedelta(minutes=1), NOW, POLICY), "t0_prestart")
        self.assertEqual(window_for(NOW + timedelta(minutes=5), NOW, POLICY), "t0_prestart")
        self.assertEqual(window_for(NOW + timedelta(minutes=10), NOW, POLICY), "close")
        self.assertEqual(window_for(NOW + timedelta(minutes=60), NOW, POLICY), "decision")

    def test_overlap_preserves_all_window_memberships(self):
        self.assertEqual(
            windows_for(NOW + timedelta(minutes=3), NOW, POLICY),
            ("t0_prestart", "close"),
        )

    def test_t0_never_admits_at_or_after_start(self):
        self.assertEqual(windows_for(NOW, NOW, POLICY), ())
        self.assertEqual(windows_for(NOW - timedelta(microseconds=1), NOW, POLICY), ())
        self.assertEqual(windows_for(NOW - timedelta(minutes=1), NOW, POLICY), ())

    def test_outside_windows_is_not_due(self):
        self.assertEqual(windows_for(NOW + timedelta(minutes=300), NOW, POLICY), ())
        self.assertEqual(windows_for(NOW + timedelta(minutes=30), NOW, POLICY), ())

    def test_due_events_selects_all_memberships(self):
        events = [
            _event("overlap", 3),
            _event("close", 10),
            _event("far", 300),
            _event("decision", 60),
            _event("started", -5),
        ]
        due = due_events(events, NOW, POLICY)
        self.assertEqual(due, {
            "overlap": ("t0_prestart", "close"),
            "close": ("close",),
            "decision": ("decision",),
        })


class RowTests(unittest.TestCase):
    def test_two_sided_market_produces_rows_labelled_not_evidence(self):
        rows, skipped = build_rows(
            "americanfootball_nfl", [_odds_event("a", 10)], {"a": ("close",)}, NOW, POLICY
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(skipped, [])
        for row in rows:
            self.assertEqual(row["evidence_class"], "NOT_EVIDENCE")
            self.assertFalse(row["promotion_authority"])
            self.assertEqual(row["window"], "close")
            self.assertEqual(row["start_guard"], START_GUARD_SCHEDULED)
            self.assertEqual(tuple(row["guard_failure_modes"]), START_GUARD_FAILURE_MODES)
            self.assertEqual(row["actual_start_status"], "UNADJUDICATED")
            self.assertTrue(row["requires_start_attestation"])
            self.assertNotIn("model_p", row)
            self.assertNotIn("evidence_unit_id", row)

    def test_overlap_duplicates_labels_but_not_observation_identity(self):
        rows, skipped = build_rows(
            "americanfootball_nfl",
            [_odds_event("a", 3)],
            {"a": ("t0_prestart", "close")},
            NOW,
            POLICY,
        )
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["window"] for row in rows}, {"t0_prestart", "close"})
        self.assertEqual(len({row["capture_id"] for row in rows}), 1)
        self.assertEqual(len({row["fetch_sha256"] for row in rows}), 1)
        for row in rows:
            self.assertEqual(row["start_guard"], START_GUARD_SCHEDULED)
            self.assertEqual(tuple(row["guard_failure_modes"]), START_GUARD_FAILURE_MODES)

    def test_t0_row_is_not_evidence_and_remains_prestart(self):
        rows, skipped = build_rows(
            "mma_mixed_martial_arts", [_odds_event("a", 1)], {"a": ("t0_prestart",)}, NOW, POLICY
        )
        self.assertEqual(skipped, [])
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["window"], "t0_prestart")
            self.assertEqual(row["evidence_class"], "NOT_EVIDENCE")
            self.assertNotIn("model_p", row)
            self.assertNotIn("evidence_unit_id", row)

    def test_started_candidate_is_skipped_with_guard_provenance(self):
        rows, skipped = build_rows(
            "mma_mixed_martial_arts", [_odds_event("a", -1)], {"a": ("t0_prestart",)}, NOW, POLICY
        )
        self.assertEqual(rows, [])
        self.assertEqual(skipped[0]["reason"], "EVENT_ALREADY_STARTED")
        self.assertEqual(skipped[0]["start_guard"], START_GUARD_SCHEDULED)
        self.assertEqual(tuple(skipped[0]["guard_failure_modes"]), START_GUARD_FAILURE_MODES)

    def test_one_sided_market_is_skipped_not_imputed(self):
        rows, skipped = build_rows(
            "americanfootball_nfl", [_odds_event("a", 10, outcomes=1)], {"a": ("close",)}, NOW, POLICY
        )
        self.assertEqual(rows, [])
        self.assertEqual(skipped[0]["reason"], "ONE_SIDED_QUOTE_NOT_IMPUTED")
        self.assertEqual(skipped[0]["start_guard"], START_GUARD_SCHEDULED)

    def test_unlisted_book_is_ignored(self):
        rows, _ = build_rows(
            "americanfootball_nfl", [_odds_event("a", 10, book="bovada")], {"a": ("close",)}, NOW, POLICY
        )
        self.assertEqual(rows, [])

    def test_event_not_due_is_not_captured(self):
        rows, _ = build_rows("americanfootball_nfl", [_odds_event("a", 10)], {}, NOW, POLICY)
        self.assertEqual(rows, [])


class RunTests(unittest.TestCase):
    def _opener(self, index_payload, odds_payload, calls):
        class Resp:
            def __init__(self, obj):
                self.raw = json.dumps(obj).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return self.raw

        def opener(url, timeout=30):
            if "/events?" in url:
                calls.append("free")
                return Resp(index_payload)
            calls.append("paid")
            return Resp(odds_payload)

        return opener

    def test_no_due_events_makes_no_paid_call(self):
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            report = run(
                now=NOW,
                policy=POLICY,
                out_dir=Path(tmp),
                keys=["k"],
                opener=self._opener([_event("a", 400)], [], calls),
            )
        self.assertNotIn("paid", calls)
        self.assertEqual(report["total_rows_written"], 0)

    def test_due_event_writes_append_only_rows(self):
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            report = run(
                now=NOW,
                policy=POLICY,
                out_dir=Path(tmp),
                keys=["k"],
                opener=self._opener([_event("a", 10)], [_odds_event("a", 10)], calls),
            )
            self.assertIn("paid", calls)
            self.assertEqual(report["total_rows_written"], 6)
            files = list(Path(tmp).rglob("*.ndjson"))
            self.assertTrue(files)
            first = files[0].read_text().strip().splitlines()
            self.assertTrue(all(json.loads(line)["evidence_class"] == "NOT_EVIDENCE" for line in first))
            self.assertTrue(all(json.loads(line)["start_guard"] == START_GUARD_SCHEDULED for line in first))

            before = files[0].read_text()
            run(
                now=NOW,
                policy=POLICY,
                out_dir=Path(tmp),
                keys=["k"],
                opener=self._opener([_event("a", 10)], [_odds_event("a", 10)], calls),
            )
            after = files[0].read_text()
            self.assertTrue(after.startswith(before), "existing captured prices must never be rewritten")

    def test_overlap_window_labels_share_capture_identity_for_all_sports(self):
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            report = run(
                now=NOW,
                policy=POLICY,
                out_dir=Path(tmp),
                keys=["k"],
                opener=self._opener([_event("a", 3)], [_odds_event("a", 3)], calls),
            )
            self.assertEqual(report["total_rows_written"], 12)
            self.assertEqual(set(report["sports"]), {"NFL", "CFB", "UFC"})
            for entry in report["sports"].values():
                self.assertEqual(entry["window_memberships_due"], 2)
                self.assertEqual(set(entry["windows"]), {"t0_prestart", "close"})
                self.assertEqual(entry["start_guard"], START_GUARD_SCHEDULED)
            for path in Path(tmp).rglob("*.ndjson"):
                parsed = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
                self.assertEqual(len({row["capture_id"] for row in parsed}), 1)

    def test_dry_run_never_calls_paid_endpoint(self):
        calls: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            run(
                now=NOW,
                policy=POLICY,
                out_dir=Path(tmp),
                keys=["k"],
                opener=self._opener([_event("a", 10)], [_odds_event("a", 10)], calls),
                dry_run=True,
            )
        self.assertNotIn("paid", calls)


if __name__ == "__main__":
    unittest.main()
