"""Contract and distribution-shape tests for the unfrozen research challenger."""
import math
import unittest

from sportsedge.sports.nfl.prop_availability_mixture_v1 import (
    MODEL_ID,
    STATUS,
    simulate_availability_mixture,
)
from sportsedge.sports.nfl.prop_role_challenger import (
    PropChallengerError,
    RoleProjection,
    simulate_player_props,
    stabilize_role,
)


EFFICIENCY = {
    "completion_rate": 0.66,
    "catch_rate": 0.68,
    "pass_td_rate": 0.052,
    "interception_rate": 0.021,
    "yards_per_attempt": 7.3,
    "yards_per_carry": 4.5,
    "yards_per_target": 8.1,
}


class AvailabilityMixtureTests(unittest.TestCase):
    def role(self, probability: float) -> RoleProjection:
        return stabilize_role(
            entity_id="p1",
            history=[],
            projected_role={"pass_attempts": 0, "rush_attempts": 0, "targets": 10},
            availability_probability=probability,
        )

    def test_full_availability_paths_match_unchanged_incumbent(self):
        role = self.role(1.0)
        incumbent = simulate_player_props(
            role=role, efficiency=EFFICIENCY, paths=200, seed=11,
        )
        challenger = simulate_availability_mixture(
            role=role, efficiency=EFFICIENCY, paths=200, seed=11,
        )
        self.assertEqual(challenger.sha256, incumbent.sha256)
        self.assertEqual(challenger.model_id, MODEL_ID)
        self.assertEqual(challenger.status, STATUS)
        self.assertNotEqual(challenger.status, "VALIDATED")

    def test_half_availability_changes_high_line_tail_not_expected_mean(self):
        role = self.role(0.5)
        incumbent = simulate_player_props(
            role=role, efficiency=EFFICIENCY, paths=4_000, seed=23,
            shared_pace_sigma=0.0,
        )
        challenger = simulate_availability_mixture(
            role=role, efficiency=EFFICIENCY, paths=4_000, seed=23,
            shared_pace_sigma=0.0,
        )
        naive_over = incumbent.probabilities("RECEPTIONS", 9.5)[0]
        mixture_over = challenger.probabilities("RECEPTIONS", 9.5)[0]
        # Targets=10 * catch_rate=.68; choose a target-count market by
        # inspecting the correlated per-path target state below instead.
        naive_target_over = sum(p["targets"] > 9.5 for p in incumbent.paths) / 4_000
        mixed_target_over = sum(p["targets"] > 9.5 for p in challenger.paths) / 4_000
        self.assertGreater(mixed_target_over, naive_target_over + 0.15)
        self.assertAlmostEqual(
            sum(p["targets"] for p in challenger.paths) / 4_000,
            5.0,
            delta=0.25,
        )
        self.assertLessEqual(naive_over, mixture_over)
        self.assertEqual(challenger.sha256, simulate_availability_mixture(
            role=role, efficiency=EFFICIENCY, paths=4_000, seed=23,
            shared_pace_sigma=0.0,
        ).sha256)

    def test_unavailable_player_has_zero_correlated_usage(self):
        out = simulate_availability_mixture(
            role=self.role(0.0), efficiency=EFFICIENCY, paths=150, seed=9,
        )
        self.assertTrue(all(all(v == 0 for v in row.values()) for row in out.paths))

    def test_invalid_availability_and_inconsistent_unconditional_mean_fail(self):
        base = self.role(1.0)
        invalid = RoleProjection(
            entity_id="p1", pass_attempt_mean=0, rush_attempt_mean=0,
            target_mean=10, availability_probability=math.nan,
            history_games=0, source="TEST",
        )
        with self.assertRaisesRegex(PropChallengerError, "BAD_AVAILABILITY_PROBABILITY"):
            simulate_availability_mixture(role=invalid, efficiency=EFFICIENCY, paths=100)
        inconsistent = RoleProjection(
            entity_id="p1", pass_attempt_mean=0, rush_attempt_mean=0,
            target_mean=10, availability_probability=0,
            history_games=0, source=base.source,
        )
        with self.assertRaisesRegex(PropChallengerError, "ZERO_AVAILABILITY_WITH_NONZERO_ROLE"):
            simulate_availability_mixture(role=inconsistent, efficiency=EFFICIENCY, paths=100)

    def test_market_inputs_still_refused_by_underlying_simulator(self):
        with self.assertRaisesRegex(PropChallengerError, "MARKET_INPUT_FORBIDDEN"):
            simulate_availability_mixture(
                role=self.role(0.5), efficiency={**EFFICIENCY, "sportsbook": "DK"},
                paths=100,
            )


if __name__ == "__main__":
    unittest.main()
