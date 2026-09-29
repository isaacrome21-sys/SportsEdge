from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import unittest

from sportsedge.mlb_source import GameSnapshot


SPEC = importlib.util.spec_from_file_location("mlb_postseason_schedule_gate", Path("scripts/mlb_postseason_schedule_gate.py"))
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MOD)


def _game(pk, start, status="Preview"):
    return GameSnapshot(
        game_pk=pk,
        game_date=start,
        status=status,
        away_id=1,
        away_name="Away",
        home_id=2,
        home_name="Home",
        away_probable_pitcher_id=None,
        away_probable_pitcher_name=None,
        home_probable_pitcher_id=None,
        home_probable_pitcher_name=None,
        retrieved_at="2026-09-29T12:00:00+00:00",
    )


class PostseasonScheduleGateTests(unittest.TestCase):
    def test_outside_window_never_fetches(self):
        def fetcher(*args, **kwargs):
            raise AssertionError("should not fetch outside active window")
        out = MOD.evaluate_postseason_gate(
            now=datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc),
            fetcher=fetcher,
        )
        self.assertFalse(out["due"])
        self.assertFalse(out["active_window"])

    def test_only_preview_game_in_t75_t45_window_is_due(self):
        def fetcher(date_text, now):
            self.assertEqual(date_text, "2026-09-29")
            return [
                _game(10, "2026-09-29T13:08:00Z"),  # 68 minutes
                _game(11, "2026-09-29T12:35:00Z"),  # 35 minutes
                _game(12, "2026-09-29T13:10:00Z", status="Final"),
            ]
        out = MOD.evaluate_postseason_gate(
            now=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
            fetcher=fetcher,
        )
        self.assertTrue(out["due"])
        self.assertEqual(out["due_game_pks"], [10])
        self.assertEqual(out["lead_window_minutes"], [45, 75])

    def test_no_due_game_is_clean_skip(self):
        out = MOD.evaluate_postseason_gate(
            now=datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc),
            fetcher=lambda *args, **kwargs: [_game(10, "2026-09-29T15:00:00Z")],
        )
        self.assertFalse(out["due"])
        self.assertEqual(out["reason"], "NO_GAME_IN_PAID_WINDOW")


if __name__ == "__main__":
    unittest.main()
