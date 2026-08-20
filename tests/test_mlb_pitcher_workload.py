import random
import unittest

from sportsedge.mlb_pa_simulator import PAProbabilities, Batter, GameConfig, simulate_game
from sportsedge.mlb_pitcher_workload import (
    PitchCountDistribution,
    PitcherWorkloadSpec,
    PitchingStaffConfig,
    PitcherWorkloadEngine,
)


def outs(prefix):
    return tuple(Batter(f"{prefix}{i}", PAProbabilities(bip_out=1.0)) for i in range(9))


class PitcherWorkloadTests(unittest.TestCase):
    def test_controller_never_assigns_bf_after_removal(self):
        staff = PitchingStaffConfig((
            PitcherWorkloadSpec("starter", hard_bf_cap=3, pitch_counts=PitchCountDistribution(((4, 1.0),))),
            PitcherWorkloadSpec("reliever", hard_bf_cap=10, pitch_counts=PitchCountDistribution(((3, 1.0),))),
        ))
        engine = PitcherWorkloadEngine(staff, random.Random(1))
        assigned = []
        for _ in range(5):
            pid = engine.assign_pitcher()
            assigned.append(pid)
            engine.record_pa(pid, outcome="BIP_OUT", outs=1, runs_charged={})
        self.assertEqual(assigned, ["starter", "starter", "starter", "reliever", "reliever"])
        snapshots = engine.snapshots()
        self.assertTrue(snapshots["starter"].removed)
        self.assertEqual(snapshots["starter"].bf, 3)
        self.assertEqual(snapshots["starter"].bf_after_removal, 0)
        self.assertEqual(snapshots["reliever"].bf, 2)

    def test_simulator_uses_workload_engine_to_choose_pitcher_for_each_pa(self):
        home_staff = PitchingStaffConfig((
            PitcherWorkloadSpec("home_starter", hard_bf_cap=3),
            PitcherWorkloadSpec("home_relief", hard_bf_cap=20),
        ))
        away_staff = PitchingStaffConfig((PitcherWorkloadSpec("away_starter", hard_bf_cap=20),))
        path = simulate_game(GameConfig(
            away=outs("a"), home=outs("h"), innings=2,
            away_pitching=away_staff, home_pitching=home_staff,
        ), random.Random(2))
        top_events = [e for e in path.pa_events if e.half == "TOP"]
        self.assertEqual([e.pitcher_id for e in top_events[:6]],
                         ["home_starter"] * 3 + ["home_relief"] * 3)
        self.assertEqual(path.pitcher_stats["home_starter"].outs, 3)
        self.assertEqual(path.pitcher_stats["home_starter"].bf, 3)
        self.assertEqual(path.pitcher_stats["home_relief"].outs, 3)

    def test_pitcher_readouts_share_pa_outcomes(self):
        k_lineup = tuple(Batter(f"k{i}", PAProbabilities(k=1.0)) for i in range(9))
        home_staff = PitchingStaffConfig((PitcherWorkloadSpec("home_p", hard_bf_cap=20),))
        away_staff = PitchingStaffConfig((PitcherWorkloadSpec("away_p", hard_bf_cap=20),))
        path = simulate_game(GameConfig(
            away=k_lineup, home=outs("h"), innings=1,
            home_pitching=home_staff, away_pitching=away_staff,
        ), random.Random(3))
        p = path.pitcher_stats["home_p"]
        self.assertEqual(p.bf, 3)
        self.assertEqual(p.outs, 3)
        self.assertEqual(p.strikeouts, 3)
        self.assertEqual(p.hits_allowed, 0)
        self.assertEqual(p.walks, 0)


if __name__ == "__main__":
    unittest.main()
