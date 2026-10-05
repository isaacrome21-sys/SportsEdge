"""Stand-in rates skip thin history and stay strictly prior."""
from __future__ import annotations

from datetime import datetime, timezone
import unittest

from sportsedge.sports.nhl.official_rate_standin import MIN_PRIOR_GAMES, prior_team_rates


def _game(i: int, home: str, away: str, hs: int, a_s: int) -> dict:
    return {
        "start_utc": f"2024-10-{10+i:02d}T00:00:00Z",
        "home_id": home,
        "away_id": away,
        "home_gf": hs,
        "away_gf": a_s,
        "home_sog": 30,
        "away_sog": 28,
        "minutes": 60.0,
    }


class PriorRateTests(unittest.TestCase):
    def test_thin_history_is_none(self):
        games = [_game(0, "1", "2", 3, 2)]
        asof = datetime(2024, 10, 20, tzinfo=timezone.utc)
        self.assertIsNone(prior_team_rates(games, team_id="1", asof=asof))

    def test_same_day_excluded(self):
        games = [_game(i, "1", "2", 3, 2) for i in range(MIN_PRIOR_GAMES)]
        asof = datetime.fromisoformat(games[-1]["start_utc"].replace("Z", "+00:00"))
        self.assertIsNone(prior_team_rates(games, team_id="1", asof=asof))

    def test_ten_prior_unlocks(self):
        games = [_game(i, "1", "2", 3, 2) for i in range(MIN_PRIOR_GAMES)]
        asof = datetime(2024, 11, 1, tzinfo=timezone.utc)
        out = prior_team_rates(games, team_id="1", asof=asof)
        self.assertIsNotNone(out)
        self.assertEqual(out["prior_games"], MIN_PRIOR_GAMES)
        self.assertGreater(out["gf60"], 0)


if __name__ == "__main__":
    unittest.main()
