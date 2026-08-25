import unittest

from sportsedge.sports.nfl.historical_validation import (
    american_implied_probability,
    build_nfl_game_evaluations,
    build_nfl_fold_rows,
    no_vig_two_way,
)


class NFLHistoricalValidationRunnerTests(unittest.TestCase):
    def _rows(self):
        rows = []
        # Four seasons, four teams. HOME1 is intentionally strong and AWAY1 weak.
        for season in range(2020, 2024):
            rows.extend([
                {
                    "game_id": f"{season}_01_A_B", "season": season, "week": 1, "game_type": "REG",
                    "gameday": f"{season}-09-01", "home_team": "A", "away_team": "B",
                    "home_score": 30, "away_score": 17, "spread_line": 3.0, "total_line": 44.0,
                    "home_spread_odds": -110, "away_spread_odds": -110,
                    "over_odds": -110, "under_odds": -110,
                },
                {
                    "game_id": f"{season}_01_C_D", "season": season, "week": 1, "game_type": "REG",
                    "gameday": f"{season}-09-02", "home_team": "C", "away_team": "D",
                    "home_score": 20, "away_score": 24, "spread_line": 1.5, "total_line": 41.5,
                    "home_spread_odds": -105, "away_spread_odds": -115,
                    "over_odds": -108, "under_odds": -112,
                },
                {
                    "game_id": f"{season}_02_A_D", "season": season, "week": 2, "game_type": "REG",
                    "gameday": f"{season}-09-08", "home_team": "A", "away_team": "D",
                    "home_score": 28, "away_score": 14, "spread_line": 4.0, "total_line": 43.0,
                    "home_spread_odds": -110, "away_spread_odds": -110,
                    "over_odds": -110, "under_odds": -110,
                },
                {
                    "game_id": f"{season}_02_C_B", "season": season, "week": 2, "game_type": "REG",
                    "gameday": f"{season}-09-09", "home_team": "C", "away_team": "B",
                    "home_score": 21, "away_score": 13, "spread_line": 2.0, "total_line": 40.0,
                    "home_spread_odds": -110, "away_spread_odds": -110,
                    "over_odds": -110, "under_odds": -110,
                },
            ])
        return rows

    def test_american_probability_and_two_way_devig(self):
        self.assertAlmostEqual(american_implied_probability(-110), 110 / 210)
        self.assertAlmostEqual(american_implied_probability(150), 100 / 250)
        a, b = no_vig_two_way(-110, -110)
        self.assertAlmostEqual(a, 0.5)
        self.assertAlmostEqual(b, 0.5)
        self.assertAlmostEqual(a + b, 1.0)

    def test_nflverse_spread_sign_is_positive_when_home_favored(self):
        evaluations = build_nfl_game_evaluations(self._rows(), min_history_seasons=1)
        row = next(item for item in evaluations if item["game_id"] == "2021_01_A_B")
        self.assertEqual(row["home_margin"], 13.0)
        self.assertEqual(row["spread_line"], 3.0)
        self.assertEqual(row["home_cover_outcome"], 1)
        self.assertEqual(row["spread_push"], False)

    def test_prediction_for_game_is_created_before_that_game_updates_state(self):
        rows = self._rows()
        baseline = build_nfl_game_evaluations(rows, min_history_seasons=1)
        changed = [dict(row) for row in rows]
        target = next(row for row in changed if row["game_id"] == "2022_01_A_B")
        target["home_score"] = 3
        target["away_score"] = 40
        mutated = build_nfl_game_evaluations(changed, min_history_seasons=1)
        before = next(item for item in baseline if item["game_id"] == "2022_01_A_B")
        after = next(item for item in mutated if item["game_id"] == "2022_01_A_B")
        self.assertEqual(before["model_margin_mu"], after["model_margin_mu"])
        self.assertEqual(before["model_total_mu"], after["model_total_mu"])
        # Later games are allowed to change because the mutated final score is then historical.
        later_before = next(item for item in baseline if item["game_id"] == "2022_02_A_D")
        later_after = next(item for item in mutated if item["game_id"] == "2022_02_A_D")
        self.assertNotEqual(later_before["model_margin_mu"], later_after["model_margin_mu"])

    def test_fold_rows_are_per_season_per_market_and_exclude_pushes(self):
        evaluations = build_nfl_game_evaluations(self._rows(), min_history_seasons=1)
        folds = build_nfl_fold_rows(evaluations)
        keys = {(row["season"], row["market"]) for row in folds}
        self.assertIn((2021, "spread"), keys)
        self.assertIn((2021, "total"), keys)
        self.assertEqual(len(keys), len(folds))
        for row in folds:
            self.assertGreater(row["n"], 0)
            self.assertGreaterEqual(row["m1_log_loss"], 0.0)
            self.assertGreaterEqual(row["m2_log_loss"], 0.0)
            self.assertGreaterEqual(row["m1_coverage"], 0.0)
            self.assertLessEqual(row["m1_coverage"], 1.0)

    def test_market_fields_do_not_change_market_blind_score_prediction(self):
        rows = self._rows()
        baseline = build_nfl_game_evaluations(rows, min_history_seasons=1)
        changed = [dict(row) for row in rows]
        target = next(row for row in changed if row["game_id"] == "2022_01_A_B")
        target["spread_line"] = 13.5
        target["total_line"] = 61.5
        target["home_spread_odds"] = 150
        target["away_spread_odds"] = -180
        mutated = build_nfl_game_evaluations(changed, min_history_seasons=1)
        before = next(item for item in baseline if item["game_id"] == "2022_01_A_B")
        after = next(item for item in mutated if item["game_id"] == "2022_01_A_B")
        self.assertEqual(before["model_margin_mu"], after["model_margin_mu"])
        self.assertEqual(before["model_total_mu"], after["model_total_mu"])
        self.assertNotEqual(before["m2_home_cover_prob"], after["m2_home_cover_prob"])


if __name__ == "__main__":
    unittest.main()
