import importlib.util
import unittest
from datetime import datetime
from pathlib import Path

from sportsedge.canonical_manual_mlb import _schedule_date_for_quote
from sportsedge.manual_quote import validate_manual_quote


SPEC = importlib.util.spec_from_file_location(
    "run_manual_mlb_snapshot", Path("scripts/run_manual_mlb_snapshot.py")
)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


BASE = {
    "game_id": "g1",
    "market_type": "MONEYLINE",
    "side": "AWAY",
    "line": 0,
    "price": -110,
    "paired_side": "HOME",
    "paired_price": 100,
    "book": "draftkings",
    "observed_at": "2026-08-19T10:00:00-05:00",
    "first_pitch_at": "2026-08-19T12:00:00-05:00",
    "source": "MANUAL",
}


class ManualMlbLiveGuardTests(unittest.TestCase):
    def test_rejects_wrong_run_date(self):
        with self.assertRaisesRegex(ValueError, "MANUAL_INPUT_DATE_MISMATCH"):
            MOD.validate_live_rows(
                [BASE], run_date="2026-08-20", max_age_minutes=30,
                as_of=datetime.fromisoformat("2026-08-19T10:10:00-05:00"),
            )

    def test_rejects_stale_quote(self):
        with self.assertRaisesRegex(ValueError, "MANUAL_QUOTE_STALE"):
            MOD.validate_live_rows(
                [BASE], run_date="2026-08-19", max_age_minutes=30,
                as_of=datetime.fromisoformat("2026-08-19T10:31:00-05:00"),
            )

    def test_rejects_started_game(self):
        with self.assertRaisesRegex(ValueError, "MANUAL_QUOTE_GAME_STARTED"):
            MOD.validate_live_rows(
                [BASE], run_date="2026-08-19", max_age_minutes=180,
                as_of=datetime.fromisoformat("2026-08-19T12:01:00-05:00"),
            )

    def test_accepts_fresh_pregame_quote(self):
        MOD.validate_live_rows(
            [BASE], run_date="2026-08-19", max_age_minutes=30,
            as_of=datetime.fromisoformat("2026-08-19T10:15:00-05:00"),
        )

    def test_canonical_schedule_date_uses_chicago_date_after_utc_rollover(self):
        row = dict(
            BASE,
            observed_at="2026-08-31T20:14:00-05:00",
            first_pitch_at="2026-08-31T20:38:00-05:00",
        )
        quote = validate_manual_quote(row)
        self.assertEqual(quote.first_pitch_at.date().isoformat(), "2026-09-01")
        self.assertEqual(_schedule_date_for_quote(quote), "2026-08-31")


if __name__ == "__main__":
    unittest.main()
