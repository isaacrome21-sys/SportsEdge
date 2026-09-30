import unittest

from scripts.audit_mlb_game_engine_dispersion import (
    REFERENCE_LINES,
    _candidate_pmf,
    _fit_dispersion_r,
    _line_prob,
)


def _total_moments(pmf: dict[str, float]) -> tuple[float, float]:
    rows = []
    for key, probability in pmf.items():
        away, home = key.split(",", 1)
        rows.append((int(away) + int(home), float(probability)))
    mean = sum(total * probability for total, probability in rows)
    variance = sum(((total - mean) ** 2) * probability for total, probability in rows)
    return mean, variance


class MLBFullGameDispersionAuditTests(unittest.TestCase):
    def test_method_of_moments_fit_recovers_known_dispersion(self):
        # With mu=8 and centered residuals +/-4, excess variance is 8 and
        # r = mu^2 / excess_variance = 64 / 8 = 8.
        rows = [
            {
                "actual_final_total": 4 if index % 2 == 0 else 12,
                "model_input_total_mean": 8.0,
            }
            for index in range(30)
        ]
        fit = _fit_dispersion_r(rows)
        self.assertEqual(fit["n"], 30)
        self.assertAlmostEqual(float(fit["mean_residual_actual_minus_input_mean"]), 0.0, places=12)
        self.assertAlmostEqual(float(fit["raw_r"]), 8.0, places=12)
        self.assertAlmostEqual(float(fit["locked_r"]), 8.0, places=12)

    def test_candidate_is_deterministic_and_overdispersed(self):
        away_mean = 4.2
        home_mean = 4.4
        regulation_input_total = away_mean + home_mean
        dispersion_r = 5.217229403204152
        candidate = _candidate_pmf(
            away_mean=away_mean,
            home_mean=home_mean,
            dispersion_r=dispersion_r,
            simulations=30000,
            identity="unit-test",
        )
        repeat = _candidate_pmf(
            away_mean=away_mean,
            home_mean=home_mean,
            dispersion_r=dispersion_r,
            simulations=30000,
            identity="unit-test",
        )

        self.assertEqual(candidate, repeat)
        self.assertAlmostEqual(sum(candidate.values()), 1.0, places=12)

        candidate_mean, candidate_variance = _total_moments(candidate)
        # The Gamma-Poisson latent pace is mean-preserving before tie resolution.
        # The final-score PMF then adds extra-innings runs on regulation ties, so
        # its mean is expected to sit modestly above the regulation input mean.
        self.assertGreater(candidate_mean, regulation_input_total)
        self.assertLess(candidate_mean, regulation_input_total + 0.60)
        # The final-score distribution must remain clearly over-dispersed rather
        # than collapsing back toward a Poisson variance near its mean.
        self.assertGreater(candidate_variance, candidate_mean * 1.20)

    def test_candidate_readouts_cover_frozen_reference_lines(self):
        pmf = _candidate_pmf(
            away_mean=4.0,
            home_mean=4.5,
            dispersion_r=5.217229403204152,
            simulations=10000,
            identity="reference-lines",
        )
        self.assertEqual(REFERENCE_LINES, (6.5, 7.5, 8.5, 9.5))
        for line in REFERENCE_LINES:
            over, under, push = _line_prob(pmf, line)
            with self.subTest(line=line):
                self.assertAlmostEqual(over + under + push, 1.0, places=12)
                self.assertGreaterEqual(over, 0.0)
                self.assertGreaterEqual(under, 0.0)
                self.assertGreaterEqual(push, 0.0)
                self.assertLessEqual(over, 1.0)
                self.assertLessEqual(under, 1.0)
                self.assertLessEqual(push, 1.0)

    def test_fit_rejects_too_small_tuning_slice(self):
        with self.assertRaisesRegex(ValueError, "at least 20"):
            _fit_dispersion_r([
                {"actual_final_total": 8, "model_input_total_mean": 8.0}
                for _ in range(19)
            ])


if __name__ == "__main__":
    unittest.main()
