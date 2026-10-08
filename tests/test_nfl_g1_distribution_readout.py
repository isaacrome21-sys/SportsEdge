import math
import unittest
from unittest.mock import patch

from sportsedge.sports.nfl.location_g1_distribution_readout import distribution_readout


def row(**changes):
    return {"season": 2025, "game_id": "one", "train_seasons": [2021, 2022, 2023, 2024],
            "home_score": 7, "away_score": 0, "predicted_margin": 3., "predicted_total": 45.,
            "spread_line": -7., "total_line": 7., **changes}


class DistributionReadoutTests(unittest.TestCase):
    def test_signed_mass_pushes_and_non_tie_brier(self):
        grid = [[0.] * 8 for _ in range(8)]
        for h, a, p in [(7, 0, .4), (0, 7, .1), (3, 0, .2), (0, 3, .1), (0, 0, .2)]:
            grid[h][a] = p
        with patch('sportsedge.sports.nfl.location_g1_distribution_readout.score_grid', return_value=grid):
            out = distribution_readout([row()])
        self.assertAlmostEqual(out['moneyline']['conditional_non_tie_brier'], .0625)
        self.assertAlmostEqual(out['markets']['spread']['win_push_loss_log_loss'], -math.log(.4))
        self.assertAlmostEqual(out['markets']['total']['win_push_loss_log_loss'], -math.log(.5))
        self.assertEqual(out['signed_key_mass']['7']['predicted'], .4)
        self.assertEqual(out['signed_key_mass']['-7']['predicted'], .1)
        self.assertFalse(out['promotion_authority'])

    def test_frozen_grid_shape_is_validated_once_and_reused(self):
        grid = [[0.] * 8 for _ in range(8)]
        grid[7][0] = 1.
        verified = {"shape": "validated-test-fixture"}
        with patch(
            'sportsedge.sports.nfl.location_g1_distribution_readout.load_freeze',
            return_value=verified,
        ) as load, patch(
            'sportsedge.sports.nfl.location_g1_distribution_readout.score_grid',
            return_value=grid,
        ) as score:
            out = distribution_readout([row(), row(game_id="two")])
        load.assert_called_once_with()
        self.assertEqual(score.call_count, 2)
        self.assertTrue(all(call.kwargs["freeze"] is verified for call in score.call_args_list))
        self.assertEqual(out["n"], 2)
        self.assertEqual(out["moneyline"]["conditional_non_tie_brier"], 0.)

    def test_real_grid_and_missing_lines(self):
        out = distribution_readout([row(spread_line=None, total_line=None)])
        self.assertEqual(out['markets']['spread']['n'], 0)
        self.assertEqual(out['markets']['spread']['missing_lines'], 1)
        self.assertTrue(0 <= out['moneyline']['conditional_non_tie_brier'] <= 1)

    def test_invalid_scores_and_overlap_fail_closed(self):
        for data in [row(home_score=7.5), row(home_score=float('nan')),
                     row(train_seasons=[2025]), row(predicted_total=200.)]:
            with self.assertRaises(ValueError):
                distribution_readout([data])
        with self.assertRaisesRegex(ValueError, 'DUPLICATE'):
            distribution_readout([row(), row()])


if __name__ == '__main__':
    unittest.main()
