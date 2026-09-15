import io
import json
import os
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from unittest.mock import patch

from scripts.nfl_2026_provider_preflight import evaluate
from scripts.odds_api_quota_guard import probe_quota


class _Response:
    def __init__(self, payload, headers=None, status=200):
        self._body = json.dumps(payload).encode("utf-8")
        self.headers = headers or {}
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._body


def _headers(remaining, used=0, last=0):
    return {
        "x-requests-remaining": str(remaining),
        "x-requests-used": str(used),
        "x-requests-last": str(last),
    }


def _http_error(code, provider_code, headers=None):
    body = json.dumps({"message": "must-not-leak", "error_code": provider_code}).encode("utf-8")
    return urllib.error.HTTPError(
        "https://example.invalid/redacted",
        code,
        "provider error",
        headers or Message(),
        io.BytesIO(body),
    )


class OddsApiQuotaGuardTests(unittest.TestCase):
    def test_all_slots_are_probed_and_best_remaining_controls_readiness(self):
        replies = iter([
            _http_error(401, "OUT_OF_USAGE_CREDITS", Message()),
            _Response([], _headers(90, used=410)),
            _Response([], _headers(40, used=460)),
        ])

        def opener(_url, timeout=30):
            return next(replies)

        report = probe_quota(
            [("SLOT_1", "secret-one"), ("SLOT_2", "secret-two"), ("SLOT_3", "secret-three")],
            minimum_remaining=76,
            opener=opener,
        )
        rendered = json.dumps(report)
        self.assertEqual(report["state"], "READY")
        self.assertEqual(report["max_remaining"], 90)
        self.assertEqual(report["ready_key_slots"], ["SLOT_2"])
        self.assertEqual(len(report["attempts"]), 3)
        self.assertNotIn("secret-one", rendered)
        self.assertNotIn("secret-two", rendered)
        self.assertNotIn("must-not-leak", rendered)

    def test_missing_quota_header_fails_closed(self):
        report = probe_quota(
            [("SLOT_1", "secret")],
            minimum_remaining=1,
            opener=lambda *_args, **_kwargs: _Response([], {"x-requests-remaining": "500"}),
        )
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "QUOTA_STATE_UNKNOWN")
        self.assertTrue(str(report["attempts"][0]["reason"]).startswith("MISSING_"))

    def test_below_reserve_is_blocked_even_on_http_200(self):
        report = probe_quota(
            [("SLOT_1", "secret")],
            minimum_remaining=76,
            opener=lambda *_args, **_kwargs: _Response([], _headers(75, used=425)),
        )
        self.assertEqual(report["state"], "BLOCKED")
        self.assertEqual(report["reason"], "INSUFFICIENT_REMAINING_CREDITS")
        self.assertEqual(report["max_remaining"], 75)


class NflProviderBudgetTests(unittest.TestCase):
    def setUp(self):
        self.capture = {
            "opener_weekday": "Tuesday",
            "opener_local_time": "09:00",
            "timezone": "America/Chicago",
            "week1_tuesday_local_date": "2026-09-08",
            "first_week": 2,
            "final_minutes_before_kickoff": 30,
        }
        self.budget = {
            "preflight_lead_minutes": 720,
            "confirmation": {"expected_request_cost_credits": 2},
            "lower_priority_paid_work": {
                "minimum_confirmation_reserve_credits": 76,
                "max_single_forward_request_cost_credits": 5,
            },
        }

    def _schedule(self, rows):
        tmp = tempfile.NamedTemporaryFile("w", newline="", delete=False)
        tmp.write("season,gameday,gametime,game_id,away_team\n")
        for row in rows:
            tmp.write(",".join(row) + "\n")
        tmp.close()
        self.addCleanup(lambda: os.unlink(tmp.name) if os.path.exists(tmp.name) else None)
        return Path(tmp.name)

    @patch.dict(os.environ, {"SPORTSEDGE_ODDS_API_KEY": "secret"}, clear=False)
    def test_week2_opener_requires_derived_76_credit_reserve(self):
        schedule = self._schedule([])

        def fake_probe(_keys, minimum_remaining):
            self.assertEqual(minimum_remaining, 76)
            return {"state": "BLOCKED", "max_remaining": 0}

        report = evaluate(
            schedule,
            datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
            self.capture,
            self.budget,
            quota_probe=fake_probe,
        )
        self.assertEqual(report["target_kind"], "OPENER")
        self.assertEqual(report["target_week"], 2)
        self.assertEqual(report["state"], "PROVIDER_BLOCKED_PREFLIGHT")
        self.assertFalse(report["immediate_capture_possible"])

    @patch.dict(os.environ, {"SPORTSEDGE_ODDS_API_KEY": "secret"}, clear=False)
    def test_forward_work_is_blocked_when_it_would_spend_into_reserve(self):
        schedule = self._schedule([])
        report = evaluate(
            schedule,
            datetime(2026, 9, 15, 10, 0, tzinfo=timezone.utc),
            self.capture,
            self.budget,
            quota_probe=lambda _keys, minimum_remaining: {"state": "READY", "max_remaining": 80},
        )
        self.assertEqual(report["state"], "PROVIDER_READY_PREFLIGHT")
        self.assertTrue(report["immediate_capture_possible"])
        self.assertFalse(report["forward_paid_allowed"])

    @patch.dict(os.environ, {"SPORTSEDGE_ODDS_API_KEY": "secret"}, clear=False)
    def test_final_target_wins_when_closer_than_next_opener(self):
        schedule = self._schedule([
            ("2026", "2026-09-17", "19:15", "game-1", "Away"),
        ])
        report = evaluate(
            schedule,
            datetime(2026, 9, 17, 18, 0, tzinfo=timezone.utc),
            self.capture,
            self.budget,
            quota_probe=lambda _keys, minimum_remaining: {"state": "READY", "max_remaining": 100},
        )
        self.assertEqual(report["target_kind"], "FINAL")
        self.assertEqual(report["target_week"], 2)
        self.assertEqual(report["state"], "PROVIDER_READY_PREFLIGHT")

    def test_no_provider_call_outside_lead_horizon(self):
        schedule = self._schedule([])

        def should_not_run(*_args, **_kwargs):
            raise AssertionError("quota probe must not run outside preflight horizon")

        report = evaluate(
            schedule,
            datetime(2026, 9, 16, 18, 0, tzinfo=timezone.utc),
            self.capture,
            self.budget,
            quota_probe=should_not_run,
        )
        self.assertEqual(report["state"], "NO_UPCOMING_PROVIDER_WINDOW")
        self.assertFalse(report["provider_probe_run"])

    def test_budget_formula_matches_frozen_capture_contract(self):
        cfg = json.loads(Path("config/nfl_2026_provider_budget_v1.json").read_text())
        c = cfg["confirmation"]
        calculated = (
            c["max_opener_attempts"] + c["max_final_attempts_per_game"] * c["max_games_per_week"]
        ) * c["expected_request_cost_credits"]
        self.assertEqual(calculated, c["derived_weekly_worst_case_reserve_credits"])
        self.assertEqual(calculated, cfg["lower_priority_paid_work"]["minimum_confirmation_reserve_credits"])


if __name__ == "__main__":
    unittest.main()
