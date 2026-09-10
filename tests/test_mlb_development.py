from __future__ import annotations

import unittest

import numpy as np

from scripts.fit_mlb_development import (
    MLBDevelopmentError,
    build_feature_sets,
    date_forward_cv_splits,
    validate_development_window,
)


class MLBDevelopmentTests(unittest.TestCase):
    def test_2021_2024_window_is_allowed(self) -> None:
        validate_development_window([2021, 2022, 2023, 2024], 2024)

    def test_2025_is_hard_forbidden(self) -> None:
        with self.assertRaisesRegex(MLBDevelopmentError, "MLB_DEV_POST_2024_FORBIDDEN"):
            validate_development_window([2021, 2022, 2023, 2024, 2025], 2024)
        with self.assertRaisesRegex(MLBDevelopmentError, "MLB_DEV_POST_2024_FORBIDDEN"):
            validate_development_window([2021, 2022, 2023, 2024], 2025)

    def test_validation_must_be_latest_development_season(self) -> None:
        with self.assertRaisesRegex(MLBDevelopmentError, "MLB_DEV_VALIDATION_MUST_BE_LATEST_SEASON"):
            validate_development_window([2021, 2022, 2023, 2024], 2023)

    def test_forward_cv_never_splits_a_calendar_date(self) -> None:
        dates: list[str] = []
        for day in range(1, 31):
            date = f"2023-04-{day:02d}"
            dates.extend([date, date])
        splits = date_forward_cv_splits(dates, folds=4)
        self.assertEqual(len(splits), 4)
        date_array = np.asarray(dates)
        for train_idx, valid_idx in splits:
            train_dates = set(date_array[train_idx])
            validation_dates = set(date_array[valid_idx])
            self.assertFalse(train_dates & validation_dates)
            self.assertLess(max(train_dates), min(validation_dates))

    def test_feature_sets_share_identical_pit_rows(self) -> None:
        games = []
        for i in range(50):
            games.append({
                "game_pk": 1000 + i,
                "date": f"2023-{4 + i // 25:02d}-{1 + i % 25:02d}",
                "home_id": 1 if i % 2 == 0 else 2,
                "away_id": 2 if i % 2 == 0 else 1,
                "home_score": 3 + (i % 5),
                "away_score": 2 + ((i * 2) % 5),
            })
        feature_sets, margin, total, dates, game_pks = build_feature_sets(games)
        baseline, baseline_names = feature_sets["baseline_v1"]
        candidate, candidate_names = feature_sets["pit_multiwindow_v1"]
        self.assertGreater(len(dates), 0)
        self.assertEqual(len(baseline), len(candidate))
        self.assertEqual(len(baseline), len(margin))
        self.assertEqual(len(total), len(game_pks))
        self.assertEqual(baseline.shape[1], len(baseline_names))
        self.assertEqual(candidate.shape[1], len(candidate_names))
        self.assertTrue(np.isfinite(baseline).all())
        self.assertTrue(np.isfinite(candidate).all())


if __name__ == "__main__":
    unittest.main()
