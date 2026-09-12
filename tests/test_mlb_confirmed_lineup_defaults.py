import inspect
import unittest

from sportsedge.auto_joint_runner import run_auto_joint_mlb
from sportsedge.auto_native_odds import run_auto_mlb_native_odds
from sportsedge.mlb_run_machine import run_mlb_machine


class MLBConfirmedLineupDefaultTests(unittest.TestCase):
    def test_production_entrypoints_require_confirmed_lineups_by_default(self):
        for fn in (run_mlb_machine, run_auto_joint_mlb, run_auto_mlb_native_odds):
            with self.subTest(function=fn.__name__):
                param = inspect.signature(fn).parameters["require_confirmed_lineup"]
                self.assertIs(param.default, True)


if __name__ == "__main__":
    unittest.main()
