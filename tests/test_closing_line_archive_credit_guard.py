import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import capture_closing_line_archive_v3 as v3

UTC = timezone.utc
NOW = datetime(2026, 9, 18, 23, 0, tzinfo=UTC)


def policy(sports=None):
    return {
        "policy_id": "CLOSING_LINE_ARCHIVE_V1",
        "sports": sports or {"CFB": "americanfootball_ncaaf"},
        "books": ["draftkings"],
        "markets": ["h2h", "spreads", "totals"],
        "regions": "us",
        "odds_format": "american",
        "windows": {"decision": {"min_minutes_before_start": 45, "max_minutes_before_start": 120}},
        "persistence": {"path_template": "archive/closing-lines/{sport_key}/{date}.ndjson"},
        "provider_budget_guard": {
            "enabled": True,
            "budget_path": "config/nfl_2026_provider_budget_v1.json",
            "paid_request_cost_credits": 3,
        },
    }


def event(event_id="g1"):
    return {
        "id": event_id,
        "commence_time": "2026-09-19T00:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
    }


def odds(event_id="g1"):
    return [{
        **event(event_id),
        "bookmakers": [{
            "key": "draftkings",
            "last_update": "2026-09-18T22:59:55Z",
            "markets": [{
                "key": "h2h",
                "outcomes": [
                    {"name": "Home", "price": -110},
                    {"name": "Away", "price": -110},
                ],
            }],
        }],
    }]


class ArchiveCreditGuardTests(unittest.TestCase):
    def test_below_79_skips_without_paid_fetch(self):
        blocked = {
            "state": "BLOCKED",
            "reason": "INSUFFICIENT_REMAINING_CREDITS",
            "minimum_remaining": 79,
            "max_remaining": 78,
            "ready_key_slots": [],
            "tested_key_slots": ["ARCHIVE_KEY_1"],
        }
        with tempfile.TemporaryDirectory() as td, \
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \
             patch.object(v3.quota_guard, "probe_quota", return_value=blocked) as probe, \
             patch.object(v3.v1, "fetch_odds") as paid:
            report = v3.run(now=NOW, policy=policy(), out_dir=Path(td), keys=["k1"], opener=None)
        paid.assert_not_called()
        self.assertEqual(probe.call_args.kwargs["minimum_remaining"], 79)
        entry = report["sports"]["CFB"]
        self.assertFalse(entry["paid_call_made"])
        self.assertTrue(entry["paid_call_skipped"])
        self.assertEqual(entry["skip_reason"], "NFL_CONFIRMATION_RESERVE_GUARD")
        self.assertEqual(entry["provider_budget_guard"]["confirmation_reserve_credits"], 76)
        self.assertEqual(entry["provider_budget_guard"]["paid_request_cost_credits"], 3)

    def test_unknown_quota_fails_closed(self):
        blocked = {
            "state": "BLOCKED",
            "reason": "QUOTA_STATE_UNKNOWN",
            "minimum_remaining": 79,
            "max_remaining": None,
            "ready_key_slots": [],
            "tested_key_slots": ["ARCHIVE_KEY_1"],
        }
        with tempfile.TemporaryDirectory() as td, \
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \
             patch.object(v3.quota_guard, "probe_quota", return_value=blocked), \
             patch.object(v3.v1, "fetch_odds") as paid:
            with self.assertRaisesRegex(Exception, "QUOTA_PREFLIGHT_BLOCKED:QUOTA_STATE_UNKNOWN"):
                v3.run(now=NOW, policy=policy(), out_dir=Path(td), keys=["k1"], opener=None)
        paid.assert_not_called()

    def test_only_ready_key_slot_can_reach_paid_fetch(self):
        ready = {
            "state": "READY",
            "reason": "RESERVE_SATISFIED",
            "minimum_remaining": 79,
            "max_remaining": 120,
            "ready_key_slots": ["ARCHIVE_KEY_2"],
            "tested_key_slots": ["ARCHIVE_KEY_1", "ARCHIVE_KEY_2"],
        }
        with tempfile.TemporaryDirectory() as td, \
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \
             patch.object(v3.quota_guard, "probe_quota", return_value=ready), \
             patch.object(v3.v1, "fetch_odds", return_value=odds()) as paid:
            report = v3.run(now=NOW, policy=policy(), out_dir=Path(td), keys=["k1", "k2"], opener=None)
        self.assertEqual(paid.call_args.args[2], ["k2"])
        self.assertTrue(report["sports"]["CFB"]["paid_call_made"])

    def test_each_due_sport_reprobes_before_its_paid_call(self):
        ready = {
            "state": "READY",
            "reason": "RESERVE_SATISFIED",
            "minimum_remaining": 79,
            "max_remaining": 120,
            "ready_key_slots": ["ARCHIVE_KEY_1"],
            "tested_key_slots": ["ARCHIVE_KEY_1"],
        }
        sports = {"NFL": "americanfootball_nfl", "CFB": "americanfootball_ncaaf"}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(v3.v1, "fetch_event_index", return_value=[event()]), \
             patch.object(v3.quota_guard, "probe_quota", return_value=ready) as probe, \
             patch.object(v3.v1, "fetch_odds", return_value=[]) as paid:
            v3.run(now=NOW, policy=policy(sports), out_dir=Path(td), keys=["k1"], opener=None)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual(paid.call_count, 2)


if __name__ == "__main__":
    unittest.main()
