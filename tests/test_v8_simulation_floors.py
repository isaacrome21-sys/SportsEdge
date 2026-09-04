from __future__ import annotations

import unittest

from sportsedge.first_hr_order_engine import DEFAULT_SIMULATIONS as FIRST_HR_SIMULATIONS
from sportsedge.shared_game_engine import V8_PRIMARY_GAME_DEFAULT_SIMULATIONS


class V8SimulationFloorTests(unittest.TestCase):
    def test_primary_game_floor(self):
        self.assertGreaterEqual(V8_PRIMARY_GAME_DEFAULT_SIMULATIONS, 100000)

    def test_first_hr_floor(self):
        self.assertGreaterEqual(FIRST_HR_SIMULATIONS, 250000)


if __name__ == "__main__":
    unittest.main()
