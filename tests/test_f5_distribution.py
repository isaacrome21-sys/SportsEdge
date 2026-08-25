import unittest

from sportsedge.f5_distribution import (
    F5DistributionError,
    build_f5_distribution,
    read_f5_probability,
)
from sportsedge.shared_f5_engine import build_shared_f5_engine_session


FEATURES = {
    "away_f5_runs_for": [0, 1, 2, 3, 1, 0, 4, 2, 1, 3],
    "away_f5_runs_against": [1, 2, 1, 0, 3, 2, 2, 4, 0, 1],
    "home_f5_runs_for": [2, 1, 3, 0, 2, 4, 1, 2, 3, 1],
    "home_f5_runs_against": [0, 2, 1, 3, 1, 2, 4, 1, 2, 0],
}


class F5DistributionTests(unittest.TestCase):
    def test_joint_distribution_conserves_probability(self):
        distribution = build_f5_distribution(FEATURES)
        self.assertAlmostEqual(sum(distribution.joint_score_pmf.values()), 1.0, places=12)

    def test_moneyline_preserves_f5_tie_as_push(self):
        distribution = build_f5_distribution(FEATURES)
        home = read_f5_probability(distribution, market="F5_MONEYLINE", side="HOME")
        away = read_f5_probability(distribution, market="F5_MONEYLINE", side="AWAY")
        self.assertAlmostEqual(
            home.probability + away.probability + home.push_probability,
            1.0,
            places=12,
        )
        self.assertAlmostEqual(home.push_probability, away.push_probability, places=12)
        self.assertGreater(home.push_probability, 0.0)

    def test_integer_total_and_team_total_preserve_push_mass(self):
        distribution = build_f5_distribution(FEATURES)
        over = read_f5_probability(distribution, market="F5_TOTALS", line=4.0, side="OVER")
        under = read_f5_probability(distribution, market="F5_TOTALS", line=4.0, side="UNDER")
        self.assertAlmostEqual(
            over.probability + under.probability + over.push_probability,
            1.0,
            places=12,
        )
        team_over = read_f5_probability(
            distribution,
            market="F5_TEAM_TOTALS",
            line=2.0,
            side="OVER",
            team_side="HOME",
        )
        team_under = read_f5_probability(
            distribution,
            market="F5_TEAM_TOTALS",
            line=2.0,
            side="UNDER",
            team_side="HOME",
        )
        self.assertAlmostEqual(
            team_over.probability + team_under.probability + team_over.push_probability,
            1.0,
            places=12,
        )

    def test_history_floor_fails_closed(self):
        bad = dict(FEATURES)
        bad["away_f5_runs_for"] = [1] * 9
        with self.assertRaises(F5DistributionError):
            build_f5_distribution(bad)

    def test_one_session_reuses_one_distribution_for_all_four_markets(self):
        calls = []

        def builder(features):
            calls.append(1)
            return build_f5_distribution(features)

        engine = build_shared_f5_engine_session(builder=builder)
        base = {
            "game_id": "g1",
            "entity_id": "g1",
            "features": FEATURES,
            "feature_source_hash": "a" * 64,
        }
        rows = [
            engine({**base, "market": "F5_MONEYLINE", "side": "HOME", "line": 0.0}),
            engine({**base, "market": "F5_RUN_LINE", "side": "HOME", "line": -0.5}),
            engine({**base, "market": "F5_TOTALS", "side": "OVER", "line": 4.5}),
            engine({**base, "entity_id": "20", "team_side": "HOME", "market": "F5_TEAM_TOTALS", "side": "OVER", "line": 2.5}),
        ]
        self.assertEqual(len(calls), 1)
        self.assertEqual(len({row["model_input_hash"] for row in rows}), 1)
        self.assertEqual(len({row["distribution_sha256"] for row in rows}), 1)
        self.assertEqual(len({row["readout_sha256"] for row in rows}), 4)
        self.assertTrue(all(row["mc_paths"] == 0 for row in rows))


if __name__ == "__main__":
    unittest.main()
