import unittest

from sportsedge.core.simulate.markets import derive_game_markets
from sportsedge.core.walkforward.season import season_walk_forward
from sportsedge.core.calibrate.isotonic import FoldSafeIsotonicCalibrator


class FootballRoadmapSevenToNineTests(unittest.TestCase):
    def test_task_7_one_joint_distribution_prices_all_supported_game_markets(self):
        rows = [
            {"home_score": 24, "away_score": 20, "first_half_home_score": 10, "first_half_away_score": 10},
            {"home_score": 17, "away_score": 20, "first_half_home_score": 7, "first_half_away_score": 13},
            {"home_score": 21, "away_score": 21, "first_half_home_score": 14, "first_half_away_score": 7},
            {"home_score": 31, "away_score": 14, "first_half_home_score": 17, "first_half_away_score": 7},
        ]
        markets = derive_game_markets(rows, spread_line=0.0, total_line=41.5, team_total_line=22.5, first_half_total_line=20.5)
        self.assertAlmostEqual(markets["moneyline"]["home_win"], 0.5)
        self.assertAlmostEqual(markets["spread"]["home_cover"], markets["moneyline"]["home_win"])
        self.assertAlmostEqual(markets["spread"]["push"], 0.25)
        self.assertAlmostEqual(markets["total"]["over"], 0.75)
        self.assertAlmostEqual(markets["team_total_home"]["over"], 0.5)
        self.assertAlmostEqual(markets["first_half_total"]["over"], 0.5)

    def test_task_7_first_half_fails_closed_when_joint_rows_do_not_contain_first_half(self):
        rows = [{"home_score": 24, "away_score": 20}]
        with self.assertRaisesRegex(ValueError, "FIRST_HALF_SCORES_MISSING"):
            derive_game_markets(rows, first_half_total_line=21.5)

    def test_task_8_walk_forward_never_places_test_season_in_training(self):
        rows = [
            {"season": 2019, "id": "a"},
            {"season": 2020, "id": "b"},
            {"season": 2021, "id": "c"},
            {"season": 2022, "id": "d"},
        ]
        folds = season_walk_forward(rows, season_key="season", min_train_seasons=2)
        self.assertEqual([f.test_season for f in folds], [2021, 2022])
        for fold in folds:
            self.assertTrue(all(row["season"] < fold.test_season for row in fold.train_rows))
            self.assertTrue(all(row["season"] == fold.test_season for row in fold.test_rows))

    def test_task_9_calibrator_rejects_test_fold_fit_and_is_monotone(self):
        calibrator = FoldSafeIsotonicCalibrator()
        with self.assertRaisesRegex(ValueError, "CALIBRATOR_FIT_ON_TEST_FOLD"):
            calibrator.fit([0.2, 0.8], [0, 1], fit_seasons={2022}, test_season=2022)

        calibrator.fit(
            [0.05, 0.20, 0.35, 0.50, 0.65, 0.80, 0.95],
            [0, 0, 1, 0, 1, 1, 1],
            fit_seasons={2019, 2020, 2021},
            test_season=2022,
        )
        transformed = calibrator.transform([0.10, 0.30, 0.60, 0.90])
        self.assertEqual(transformed, sorted(transformed))
        self.assertTrue(all(0.0 <= x <= 1.0 for x in transformed))


if __name__ == "__main__":
    unittest.main()
