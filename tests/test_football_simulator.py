import unittest


class FootballSimulatorTests(unittest.TestCase):
    def test_key_number_mixture_preserves_empirical_mass(self):
        from sportsedge.core.simulate.football import KeyNumberMarginModel

        empirical = {-7: 0.07, -3: 0.09, 3: 0.10, 7: 0.08}
        model = KeyNumberMarginModel(mean=0.0, sigma=13.4, empirical_key_mass=empirical)
        pmf = model.margin_pmf(range(-60, 61))

        self.assertAlmostEqual(sum(pmf.values()), 1.0, places=10)
        for margin, target in empirical.items():
            self.assertAlmostEqual(pmf[margin], target, delta=0.002)

    def test_joint_score_simulator_returns_integer_nonnegative_scores(self):
        from sportsedge.core.simulate.football import JointScoreSimulator, KeyNumberMarginModel

        model = KeyNumberMarginModel(
            mean=3.0,
            sigma=13.4,
            empirical_key_mass={-7: 0.05, -3: 0.08, 3: 0.11, 7: 0.09},
        )
        sim = JointScoreSimulator(margin_model=model, total_mean=46.0, total_sigma=10.0, seed=7)
        rows = sim.simulate(2000)
        self.assertEqual(len(rows), 2000)
        for row in rows:
            self.assertIsInstance(row["home_score"], int)
            self.assertIsInstance(row["away_score"], int)
            self.assertGreaterEqual(row["home_score"], 0)
            self.assertGreaterEqual(row["away_score"], 0)
            self.assertEqual(row["margin"], row["home_score"] - row["away_score"])
            self.assertEqual(row["total"], row["home_score"] + row["away_score"])


if __name__ == "__main__":
    unittest.main()
