from __future__ import annotations

import unittest

from sportsedge.sports.nfl.m2_v2_selection import DEFAULT_NFL_M2_V2_KERNEL_GRID
from sportsedge.sports.nfl.m2_v2c_validation import (
    NFL_M2_V2C_KERNEL_GRID,
    NFL_M2_V2C_SELECTION_CONTRACT,
    NFL_M2_V2C_VARIANT_ID,
)


class TestNFLM2V2CContract(unittest.TestCase):
    def test_v2c_is_a_new_contract_not_a_retroactive_v2a_grid_change(self):
        self.assertEqual(
            DEFAULT_NFL_M2_V2_KERNEL_GRID,
            (0.50, 0.75, 1.00, 1.25, 1.50, 2.00),
        )
        self.assertEqual(NFL_M2_V2C_KERNEL_GRID[:4], (0.20, 0.30, 0.40, 0.50))
        self.assertLess(min(NFL_M2_V2C_KERNEL_GRID), min(DEFAULT_NFL_M2_V2_KERNEL_GRID))
        self.assertEqual(len(set(NFL_M2_V2C_KERNEL_GRID)), len(NFL_M2_V2C_KERNEL_GRID))

    def test_v2c_identity_is_explicit(self):
        self.assertEqual(
            NFL_M2_V2C_SELECTION_CONTRACT,
            "NFL_M2_V2C_EXPANDED_TRAINING_ONLY_KERNEL_SELECTION_V1",
        )
        self.assertEqual(
            NFL_M2_V2C_VARIANT_ID,
            "nfl_m2_v2c_expanded_bandwidth_candidate",
        )

    def test_grid_is_positive_sorted_and_contains_original_grid(self):
        self.assertEqual(tuple(sorted(NFL_M2_V2C_KERNEL_GRID)), NFL_M2_V2C_KERNEL_GRID)
        self.assertTrue(all(value > 0.0 for value in NFL_M2_V2C_KERNEL_GRID))
        self.assertTrue(set(DEFAULT_NFL_M2_V2_KERNEL_GRID).issubset(NFL_M2_V2C_KERNEL_GRID))


if __name__ == "__main__":
    unittest.main()
