import unittest

import scripts.rebuild_game_nrfi_models as core
import scripts.rebuild_game_nrfi_models_v3 as rebuild


class RebuildCutoffChronologyTests(unittest.TestCase):
    def test_doubleheader_second_game_cannot_see_first_game_final(self):
        games = [
            {"game_pk": 1, "officialDate": "2026-07-04", "date": "2026-07-04", "year": 2026, "month": 7, "away_id": 10, "home_id": 20, "away_runs": 1, "home_runs": 2, "away_fi": 0, "home_fi": 0},
            {"game_pk": 2, "officialDate": "2026-07-04", "date": "2026-07-04", "year": 2026, "month": 7, "away_id": 10, "home_id": 20, "away_runs": 9, "home_runs": 8, "away_fi": 1, "home_fi": 1},
            {"game_pk": 3, "officialDate": "2026-07-05", "date": "2026-07-05", "year": 2026, "month": 7, "away_id": 10, "home_id": 20, "away_runs": 3, "home_runs": 4, "away_fi": 0, "home_fi": 1},
        ]
        out = rebuild.build_features_cutoff(games)
        season_games_idx = core.RUN_FEATURES.index("season_games")

        # Two team rows per game. Both July 4 games must see exactly the same
        # prior-day history: zero games for both teams.
        self.assertEqual(out["run_X"][0, season_games_idx], 0.0)
        self.assertEqual(out["run_X"][1, season_games_idx], 0.0)
        self.assertEqual(out["run_X"][2, season_games_idx], 0.0)
        self.assertEqual(out["run_X"][3, season_games_idx], 0.0)

        # The next date may see both July 4 finals, so each team has two games.
        self.assertEqual(out["run_X"][4, season_games_idx], 2.0)
        self.assertEqual(out["run_X"][5, season_games_idx], 2.0)

        # With identical teams/home-away roles, same-date FI features must be
        # byte-for-byte/equality identical despite different Game 1 finals.
        self.assertTrue((out["fi_X"][0] == out["fi_X"][1]).all())

    def test_build_is_deterministic_for_sorted_input(self):
        games = [
            {"game_pk": 1, "officialDate": "2026-07-04", "date": "2026-07-04", "year": 2026, "month": 7, "away_id": 10, "home_id": 20, "away_runs": 1, "home_runs": 2, "away_fi": 0, "home_fi": 0},
            {"game_pk": 2, "officialDate": "2026-07-05", "date": "2026-07-05", "year": 2026, "month": 7, "away_id": 20, "home_id": 10, "away_runs": 2, "home_runs": 3, "away_fi": 0, "home_fi": 1},
        ]
        first = rebuild.build_features_cutoff(games)
        second = rebuild.build_features_cutoff(games)
        for key in first:
            self.assertTrue((first[key] == second[key]).all(), key)


if __name__ == "__main__":
    unittest.main()
