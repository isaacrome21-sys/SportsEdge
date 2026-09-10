import unittest
from unittest.mock import patch

from sportsedge.sports.nfl.m2_v2_selection import select_nfl_m2_v2_kernel_scale


class TestNFLM2V2KernelSelection(unittest.TestCase):
    def test_earliest_outer_window_uses_preregistered_fallback_without_peeking(self):
        rows = [{"season": 2016}, {"season": 2017}]
        result = select_nfl_m2_v2_kernel_scale(rows, candidate_scales=(0.5, 1.0, 1.5))
        self.assertEqual(result.selected_scale, 1.0)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.scored_observations, 0)
        self.assertFalse(result.to_dict()["outer_test_data_used"])
        self.assertFalse(result.to_dict()["historical_key_target_used"])

    def test_selection_uses_inner_loss_and_deterministic_tie_break_only(self):
        rows = [{"season": 2016}, {"season": 2017}, {"season": 2018}]
        def fake_score(_rows, *, scale, ridge_alpha, min_inner_train_seasons):
            losses = {0.5: 0.62, 1.0: 0.58, 1.5: 0.58}
            return losses[scale], 100, (2018,)
        with patch("sportsedge.sports.nfl.m2_v2_selection._score_scale_on_inner_folds", side_effect=fake_score):
            result = select_nfl_m2_v2_kernel_scale(rows, candidate_scales=(0.5, 1.0, 1.5))
        self.assertEqual(result.selected_scale, 1.0)
        self.assertFalse(result.fallback_used)
        self.assertEqual(result.criterion, "INNER_SPREAD_TOTAL_LOG_LOSS")
        self.assertEqual(result.inner_test_seasons, (2018,))
        self.assertFalse(result.to_dict()["historical_key_target_used"])

    def test_duplicate_or_invalid_grid_fails_closed(self):
        rows = [{"season": 2016}, {"season": 2017}, {"season": 2018}]
        with self.assertRaisesRegex(ValueError, "GRID_DUPLICATE"):
            select_nfl_m2_v2_kernel_scale(rows, candidate_scales=(1.0, 1.0))
        with self.assertRaisesRegex(ValueError, "GRID_INVALID"):
            select_nfl_m2_v2_kernel_scale(rows, candidate_scales=(0.0, 1.0))

    def test_no_scored_inner_rows_falls_back_instead_of_using_outer_evidence(self):
        rows = [{"season": 2016}, {"season": 2017}, {"season": 2018}]
        with patch("sportsedge.sports.nfl.m2_v2_selection._score_scale_on_inner_folds", return_value=(None, 0, (2018,))):
            result = select_nfl_m2_v2_kernel_scale(rows, candidate_scales=(0.5, 1.0, 1.5))
        self.assertEqual(result.selected_scale, 1.0)
        self.assertTrue(result.fallback_used)
        self.assertEqual(result.inner_test_seasons, (2018,))


if __name__ == "__main__":
    unittest.main()
