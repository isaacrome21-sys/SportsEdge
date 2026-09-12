import unittest

from sportsedge.sports.nfl.m2_v2_selector import (
    DEFAULT_KERNEL_SCALE_GRID,
    NFL_M2_V2_SELECTOR_CONTRACT,
)


class NFLM2V2GridContractTests(unittest.TestCase):
    def test_v2_diagnostic_selector_identity_and_grid_are_frozen(self):
        self.assertEqual(
            NFL_M2_V2_SELECTOR_CONTRACT,
            "NFL_M2_V2_NESTED_TRAINING_KERNEL_SELECTOR_V2",
        )
        self.assertEqual(
            DEFAULT_KERNEL_SCALE_GRID,
            (0.25, 0.35, 0.50, 0.75, 1.00, 1.25, 1.50, 2.00),
        )
        self.assertEqual(tuple(sorted(set(DEFAULT_KERNEL_SCALE_GRID))), DEFAULT_KERNEL_SCALE_GRID)
        self.assertTrue(all(scale > 0.0 for scale in DEFAULT_KERNEL_SCALE_GRID))


if __name__ == "__main__":
    unittest.main()
