"""Fail-closed Attempt 9 live rules: no fallback, no integer lines."""
from __future__ import annotations

from datetime import date
import unittest

from sportsedge.nfl_attempt9_live_forecast import (
    NO_MODEL_HISTORY,
    NO_MODEL_INTEGER,
    NO_MODEL_MONEYLINE,
    load_runtime,
    market_eligibility,
    raw_forecasts,
    recency_features,
)
from sportsedge.nfl_lines_intake import NflLinesIntakeError, parse_nfl_lines


class EligibilityTests(unittest.TestCase):
    def test_moneyline_blocked(self):
        self.assertEqual(market_eligibility("moneyline", None), NO_MODEL_MONEYLINE)

    def test_integer_spread_blocked(self):
        self.assertEqual(market_eligibility("spread", 3.0), NO_MODEL_INTEGER)
        self.assertEqual(market_eligibility("spread", -7.0), NO_MODEL_INTEGER)

    def test_half_point_spread_open(self):
        self.assertIsNone(market_eligibility("spread", -3.5))
        self.assertIsNone(market_eligibility("total", 47.5))


class HistoryTests(unittest.TestCase):
    def test_short_history_is_no_model(self):
        games = [
            {"date": "2026-09-10", "id": "1", "home": "KC", "away": "BAL", "hs": 27, "as": 20},
        ]
        out = recency_features(games, home="KC", away="BAL", asof=date(2026, 9, 21))
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], NO_MODEL_HISTORY)

    def test_five_games_unlocks_features(self):
        games = []
        for i in range(5):
            games.append({"date": f"2026-09-0{i+1}" if i < 9 else f"2026-09-{i+1}", "id": str(i), "home": "KC", "away": "LV", "hs": 24 + i, "as": 17})
            games.append({"date": f"2026-08-0{i+1}" if i < 9 else f"2026-08-{i+1}", "id": f"a{i}", "home": "BAL", "away": "CIN", "hs": 21, "as": 20})
        out = recency_features(games, home="KC", away="BAL", asof=date(2026, 9, 20))
        self.assertTrue(out["ok"])
        runtime = load_runtime()
        forecast = raw_forecasts(runtime, out["vector"])
        self.assertIn("margin", forecast)
        self.assertIn("total", forecast)


class IntakeTests(unittest.TestCase):
    def test_both_sides_required(self):
        with self.assertRaises(NflLinesIntakeError):
            parse_nfl_lines("Chiefs @ Ravens\nSpread +3.5 -110")

    def test_parses_half_point_ticket(self):
        tickets = parse_nfl_lines("Chiefs @ Ravens\nSpread +3.5 -110 -108\nTotal 47.5 -105 -115")
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].markets[0].line, 3.5)


if __name__ == "__main__":
    unittest.main()
