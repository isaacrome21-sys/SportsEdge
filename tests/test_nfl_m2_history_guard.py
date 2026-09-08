import unittest
from unittest.mock import patch

from sportsedge.sports.nfl.m2_history_guard import build_nfl_m2_history_rows


class NFLM2HistoryGuardTests(unittest.TestCase):
    def _game(self, gid, season, week, day):
        return {
            "game_id": gid,
            "season": season,
            "week": week,
            "game_type": "REG",
            "gameday": day,
            "gametime": "13:00",
            "home_team": "HME",
            "away_team": "AWY",
        }

    def _complete_game_pbp(self, gid):
        return [
            {"game_id": gid, "play_id": 1, "posteam": "HME", "defteam": "AWY", "epa": 0.2,
             "pass": 1, "rush": 0, "qb_dropback": 1, "passer_player_id": "H_QB"},
            {"game_id": gid, "play_id": 2, "posteam": "HME", "defteam": "AWY", "epa": -0.1,
             "pass": 0, "rush": 1, "qb_dropback": 0},
            {"game_id": gid, "play_id": 3, "posteam": "AWY", "defteam": "HME", "epa": 0.1,
             "pass": 1, "rush": 0, "qb_dropback": 1, "passer_player_id": "A_QB"},
            {"game_id": gid, "play_id": 4, "posteam": "AWY", "defteam": "HME", "epa": -0.2,
             "pass": 0, "rush": 1, "qb_dropback": 0},
        ]

    def _participation(self, gid):
        return [
            {"nflverse_game_id": gid, "play_id": 1, "was_pressure": False},
            {"nflverse_game_id": gid, "play_id": 3, "was_pressure": True},
        ]

    def _fake_row(self, game):
        return {
            "game_id": game["game_id"],
            "season": game["season"],
            "week": game["week"],
            "home_features": {"qb_id": "H_QB", "off_epa": 0.0, "pressure_for": 0.0},
            "away_features": {"qb_id": "A_QB", "off_epa": 0.0, "pressure_for": 0.0},
        }

    def test_missing_history_cannot_become_valid_zero_feature_row(self):
        game = self._game("2026_01_AWY_HME", 2026, 1, "2026-09-10")
        with patch(
            "sportsedge.sports.nfl.m2_history_guard._build_core_history_rows",
            return_value=[self._fake_row(game)],
        ):
            rows = build_nfl_m2_history_rows(
                [game], self._complete_game_pbp(game["game_id"]), self._participation(game["game_id"]),
                [], [], prior_decay_curves={2026: {1: 1.0}},
            )
        self.assertEqual(rows, [])

    def test_observed_zero_features_are_allowed_once_denominators_exist(self):
        prior = self._game("2025_18_AWY_HME", 2025, 18, "2026-01-04")
        week1 = self._game("2026_01_AWY_HME", 2026, 1, "2026-09-10")
        week2 = self._game("2026_02_AWY_HME", 2026, 2, "2026-09-17")
        schedule = [prior, week1, week2]
        pbp = self._complete_game_pbp(prior["game_id"]) + self._complete_game_pbp(week1["game_id"])
        participation = self._participation(prior["game_id"]) + self._participation(week1["game_id"])

        # The low-level row intentionally contains legitimate observed zeros.
        # The guard must distinguish those from unavailable history using source
        # denominators, not by inspecting the numeric feature value.
        fake = self._fake_row(week2)
        with patch(
            "sportsedge.sports.nfl.m2_history_guard._build_core_history_rows",
            return_value=[fake],
        ):
            rows = build_nfl_m2_history_rows(
                schedule, pbp, participation, [], [], prior_decay_curves={2026: {2: 0.5}},
            )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], week2["game_id"])
        self.assertEqual(rows[0]["history_availability_status"], "AVAILABLE")
        self.assertEqual(rows[0]["history_zero_fill_guard"], "PASS")
        self.assertEqual(rows[0]["home_features"]["off_epa"], 0.0)


if __name__ == "__main__":
    unittest.main()
