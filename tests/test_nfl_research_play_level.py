import unittest

from sportsedge.sports.nfl.research_play_level import build_lagged_team_game_features


class NFLResearchPlayLevelTests(unittest.TestCase):
    def test_target_game_is_not_in_its_own_features(self):
        rows = [
            {"season": 2024, "game_id": "g1", "posteam": "CHI", "play_type": "pass", "epa": 1.0, "success": 1, "yards_gained": 20, "down": 1, "cpoe": 5.0},
            {"season": 2024, "game_id": "g1", "posteam": "CHI", "play_type": "run", "epa": -1.0, "success": 0, "yards_gained": 2, "down": 2},
            {"season": 2024, "game_id": "g1", "posteam": "GB", "play_type": "pass", "epa": 0.5, "success": 1, "yards_gained": 8, "down": 1, "cpoe": 2.0},
            {"season": 2024, "game_id": "g2", "posteam": "CHI", "play_type": "pass", "epa": 100.0, "success": 1, "yards_gained": 99, "down": 1, "cpoe": 99.0},
            {"season": 2024, "game_id": "g2", "posteam": "GB", "play_type": "run", "epa": -100.0, "success": 0, "yards_gained": -5, "down": 1},
        ]
        out = build_lagged_team_game_features(rows, window_games=6)
        chi = next(x for x in out if x.game_id == "g2" and x.team == "CHI")
        self.assertEqual(chi.prior_games, 1)
        self.assertAlmostEqual(chi.lagged_epa_per_play, 0.0)
        self.assertAlmostEqual(chi.lagged_qb_cpoe, 5.0)
        self.assertNotEqual(chi.lagged_epa_per_play, 100.0)

    def test_rolling_window_is_prior_games_only(self):
        rows = []
        for i, epa in enumerate([1.0, 3.0, 9.0], start=1):
            rows.append({"season": 2024, "game_id": f"g{i}", "posteam": "DET", "play_type": "pass", "epa": epa, "success": 1, "yards_gained": 10, "down": 1, "cpoe": epa})
        out = build_lagged_team_game_features(rows, window_games=2)
        g3 = next(x for x in out if x.game_id == "g3")
        self.assertEqual(g3.prior_games, 2)
        self.assertAlmostEqual(g3.lagged_epa_per_play, 2.0)
        self.assertAlmostEqual(g3.lagged_qb_cpoe, 2.0)

    def test_future_or_prospective_season_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "NFL_RESEARCH_SEASON_NOT_ALLOWED:2025"):
            build_lagged_team_game_features([
                {"season": 2025, "game_id": "x", "posteam": "CHI", "play_type": "pass", "epa": 0.0}
            ])

    def test_missing_game_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "NFL_RESEARCH_GAME_ID_REQUIRED"):
            build_lagged_team_game_features([
                {"season": 2024, "posteam": "CHI", "play_type": "pass", "epa": 0.0}
            ])


if __name__ == "__main__":
    unittest.main()
