import unittest

from sportsedge.shared_game_engine import build_shared_game_engine_session
from sportsedge.v7_distribution import (
    DEFAULT_FULL_GAME_DISPERSION_R,
    FULL_GAME_MODE_LEGACY_LOGNORMAL,
    FULL_GAME_MODE_SHARED_GAMMA_POISSON,
    LEGACY_SHARED_GAME_SIGMA,
    LEGACY_TEAM_SIGMA,
    V7DistributionError,
    simulate_game_distribution,
)


def _total_variance(pmf: dict[str, float]) -> float:
    rows = []
    for key, p in pmf.items():
        away, home = key.split(",", 1)
        rows.append((int(away) + int(home), float(p)))
    mean = sum(total * p for total, p in rows)
    return sum(((total - mean) ** 2) * p for total, p in rows)


class MLBFullGameDispersionTests(unittest.TestCase):
    def test_low_level_default_remains_legacy_for_replay_compatibility(self):
        result = simulate_game_distribution(
            away_mean_runs=4.2,
            home_mean_runs=4.4,
            total_line=7.5,
            simulations=5000,
            seed=11,
        )
        self.assertEqual(result.full_game_distribution_mode, FULL_GAME_MODE_LEGACY_LOGNORMAL)
        self.assertIsNone(result.full_game_dispersion_r)
        self.assertEqual(result.shared_game_sigma, LEGACY_SHARED_GAME_SIGMA)
        self.assertEqual(result.team_sigma, LEGACY_TEAM_SIGMA)

    def test_validated_mode_is_mean_preserving_and_wider_than_legacy(self):
        legacy = simulate_game_distribution(
            away_mean_runs=4.2,
            home_mean_runs=4.4,
            total_line=7.5,
            simulations=50000,
            seed=22,
        )
        candidate = simulate_game_distribution(
            away_mean_runs=4.2,
            home_mean_runs=4.4,
            total_line=7.5,
            simulations=50000,
            seed=22,
            shared_game_sigma=0.0,
            team_sigma=0.0,
            full_game_dispersion_r=DEFAULT_FULL_GAME_DISPERSION_R,
        )
        self.assertEqual(candidate.full_game_distribution_mode, FULL_GAME_MODE_SHARED_GAMMA_POISSON)
        self.assertEqual(candidate.full_game_dispersion_r, DEFAULT_FULL_GAME_DISPERSION_R)
        self.assertAlmostEqual(candidate.away_mean_runs, legacy.away_mean_runs, delta=0.20)
        self.assertAlmostEqual(candidate.home_mean_runs, legacy.home_mean_runs, delta=0.20)
        self.assertGreater(_total_variance(candidate.joint_score_pmf), _total_variance(legacy.joint_score_pmf) * 1.25)
        # First-inning model is deliberately untouched by the full-game change.
        self.assertEqual(candidate.nrfi_probability, legacy.nrfi_probability)
        self.assertEqual(candidate.yrfi_probability, legacy.yrfi_probability)

    def test_validated_mode_cannot_stack_unvalidated_lognormal_noise(self):
        with self.assertRaisesRegex(V7DistributionError, "cannot be stacked"):
            simulate_game_distribution(
                away_mean_runs=4.2,
                home_mean_runs=4.4,
                total_line=7.5,
                simulations=1000,
                seed=33,
                full_game_dispersion_r=DEFAULT_FULL_GAME_DISPERSION_R,
            )

    def test_shared_production_engine_explicitly_selects_frozen_mode(self):
        seen = {}

        def simulator(**kwargs):
            seen.update(kwargs)
            return simulate_game_distribution(**kwargs)

        engine = build_shared_game_engine_session(
            simulator=simulator,
            _minimum_simulations_for_test=1000,
        )
        result = engine({
            "game_id": "dispersion-test",
            "market": "TOTALS",
            "line": 7.5,
            "side": "OVER",
            "away_mean_runs": 4.2,
            "home_mean_runs": 4.4,
            "feature_source_hash": "a" * 64,
            "simulations": 1000,
        })
        self.assertEqual(seen["full_game_dispersion_r"], DEFAULT_FULL_GAME_DISPERSION_R)
        self.assertEqual(seen["shared_game_sigma"], 0.0)
        self.assertEqual(seen["team_sigma"], 0.0)
        self.assertEqual(result["full_game_distribution_mode"], FULL_GAME_MODE_SHARED_GAMMA_POISSON)
        self.assertEqual(result["full_game_dispersion_r"], DEFAULT_FULL_GAME_DISPERSION_R)


if __name__ == "__main__":
    unittest.main()
