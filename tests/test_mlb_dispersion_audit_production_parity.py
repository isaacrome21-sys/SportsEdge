"""Parity lock: audit candidate vs production v7 path for total-run line probs.

The held-out audit validated scripts/audit_mlb_game_engine_dispersion._candidate_pmf.
Production ships the same shape through sportsedge.v7_distribution.simulate_game_distribution
with full_game_dispersion_r. This test requires their total-run line probabilities to
agree within simulation noise for the same inputs and frozen r.
"""
from __future__ import annotations

import unittest

from scripts.audit_mlb_game_engine_dispersion import REFERENCE_LINES, _candidate_pmf, _line_prob
from sportsedge.v7_distribution import (
    DEFAULT_FULL_GAME_DISPERSION_R,
    FULL_GAME_MODE_SHARED_GAMMA_POISSON,
    simulate_game_distribution,
)


class AuditProductionDispersionParityTests(unittest.TestCase):
    def test_total_line_probabilities_agree_within_noise(self):
        away_mean = 4.2
        home_mean = 4.4
        simulations = 40000
        dispersion_r = DEFAULT_FULL_GAME_DISPERSION_R

        audit_pmf = _candidate_pmf(
            away_mean=away_mean,
            home_mean=home_mean,
            dispersion_r=dispersion_r,
            simulations=simulations,
            identity="parity-lock",
        )
        production = simulate_game_distribution(
            away_mean_runs=away_mean,
            home_mean_runs=home_mean,
            total_line=0.0,
            simulations=simulations,
            seed=4242,
            shared_game_sigma=0.0,
            team_sigma=0.0,
            full_game_dispersion_r=dispersion_r,
        )
        self.assertEqual(production.full_game_distribution_mode, FULL_GAME_MODE_SHARED_GAMMA_POISSON)
        self.assertEqual(production.full_game_dispersion_r, dispersion_r)

        # Different RNG streams → compare line probs, not exact PMF equality.
        for line in REFERENCE_LINES:
            a_over, a_under, a_push = _line_prob(audit_pmf, line)
            p_over, p_under, p_push = _line_prob(production.joint_score_pmf, line)
            with self.subTest(line=line):
                self.assertAlmostEqual(a_over + a_under + a_push, 1.0, places=10)
                self.assertAlmostEqual(p_over + p_under + p_push, 1.0, places=10)
                self.assertAlmostEqual(a_over, p_over, delta=0.025)
                self.assertAlmostEqual(a_under, p_under, delta=0.025)


if __name__ == "__main__":
    unittest.main()
