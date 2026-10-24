"""Regression tests: a failed/partial CFBD pull cannot validate a blend."""
import json
import tempfile
import unittest
from pathlib import Path

from scripts import backtest_cfb_matchup_blend as backtest


class BacktestFailClosedTests(unittest.TestCase):
    def run_games(self, games, seasons="2024,2025,2026"):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d) / "games.json"
            out = Path(d) / "result.json"
            data.write_text(json.dumps(games))
            status = backtest.main([
                "--seasons", seasons, "--games-json", str(data),
                "--output", str(out),
            ])
            return status, out.exists()

    def test_empty_fetch_cannot_report_success(self):
        status, exists = self.run_games([])
        self.assertEqual(status, 1)
        self.assertFalse(exists)

    def test_missing_middle_season_cannot_choose_weight(self):
        games = [
            {"season": 2024, "id": "a"},
            {"season": 2026, "id": "b"},
        ]
        status, exists = self.run_games(games)
        self.assertEqual(status, 1)
        self.assertFalse(exists)

    def test_all_seasons_but_insufficient_history_cannot_choose_weight(self):
        games = [
            {"season": season, "week": 1, "start": f"{season}-09-01",
             "id": str(season), "home": "A", "away": "B",
             "hs": 24, "as": 17, "spread": -3.5, "total": 42.5}
            for season in (2024, 2025, 2026)
        ]
        status, exists = self.run_games(games)
        self.assertEqual(status, 1)
        self.assertFalse(exists)


if __name__ == "__main__":
    unittest.main()
