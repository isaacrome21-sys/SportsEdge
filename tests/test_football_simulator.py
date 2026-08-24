import unittest


class FootballSimulatorTests(unittest.TestCase):
    def test_imposed_key_number_mass_is_rejected(self):
        from sportsedge.core.simulate.football import KeyNumberMarginModel

        empirical = {-7: 0.07, -3: 0.09, 3: 0.10, 7: 0.08}
        with self.assertRaisesRegex(ValueError, "IMPOSED_KEY_MASS_PROHIBITED"):
            KeyNumberMarginModel(mean=0.0, sigma=13.4, empirical_key_mass=empirical)

    def test_margin_pmf_is_normalized_without_special_key_injection(self):
        from sportsedge.core.simulate.football import KeyNumberMarginModel

        model = KeyNumberMarginModel(mean=0.0, sigma=13.4)
        pmf = model.margin_pmf(range(-60, 61))
        self.assertAlmostEqual(sum(pmf.values()), 1.0, places=10)
        # Symmetric candidate around zero; ±3 and ±7 are ordinary emergent bins.
        self.assertAlmostEqual(pmf[3], pmf[-3], places=12)
        self.assertAlmostEqual(pmf[7], pmf[-7], places=12)
        self.assertGreater(pmf[3], 0.0)
        self.assertGreater(pmf[7], 0.0)

    def test_joint_score_simulator_requires_explicit_seed(self):
        from sportsedge.core.simulate.football import JointScoreSimulator, KeyNumberMarginModel

        model = KeyNumberMarginModel(mean=3.0, sigma=13.4)
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            JointScoreSimulator(margin_model=model, total_mean=46.0, total_sigma=10.0)

    def test_joint_score_simulator_returns_integer_nonnegative_scores(self):
        from sportsedge.core.simulate.football import JointScoreSimulator, KeyNumberMarginModel

        model = KeyNumberMarginModel(mean=3.0, sigma=13.4)
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

    def test_smooth_candidate_is_blocked_by_emergent_key_attestation(self):
        from collections import Counter
        from sportsedge.core.simulate.football import JointScoreSimulator, KeyNumberMarginModel
        from sportsedge.core.validation.math_attestation import attest_validated_math

        model = KeyNumberMarginModel(mean=-2.5, sigma=13.5)
        rows = JointScoreSimulator(
            margin_model=model, total_mean=45.5, total_sigma=10.5, seed=20260823,
        ).simulate(100000)
        counts = Counter(row["margin"] for row in rows)
        simulated = {key: counts[key] / len(rows) for key in (-7, -3, 3, 7)}

        # Representative key-number validation targets are deliberately external
        # to the simulator. The smooth score-level candidate must not certify
        # itself merely because it runs; it should fail when emergent key mass is
        # materially below historical-style targets.
        targets = {-7: 0.060, -3: 0.080, 3: 0.090, 7: 0.065}
        errors = {str(key): abs(simulated[key] - targets[key]) for key in targets}
        artifact = {
            "provenance": "REAL_PUBLIC_HISTORY",
            "source_sha256": "a" * 64,
            "profile_version": "smooth_candidate_behavioral_test_v1",
            "key_number_contract": "EMERGENT_VALIDATION_TARGET_V1",
            "seasons": [2024, 2025],
            "key_numbers": [-7, -3, 3, 7],
            "max_allowed_abs_error": 0.01,
            "per_key_abs_error": errors,
        }
        result = attest_validated_math(artifact)
        self.assertFalse(result["math_valid"])
        self.assertEqual(result["attestation"], "BLOCKED_MATH")
        self.assertTrue(result["failed_keys"])


if __name__ == "__main__":
    unittest.main()
