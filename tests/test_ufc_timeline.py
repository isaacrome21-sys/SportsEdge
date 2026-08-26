import unittest

from sportsedge.ufc_timeline import (
    UFCFighterTimelineProfile,
    effective_rates,
    n_way_devig,
    pairwise_style_multipliers,
    simulate_fight_distribution,
    simulate_fight_timeline,
)


def fighter(fid, **kwargs):
    base = dict(
        fighter_id=fid,
        name=fid,
        ko_hazard_per_min=0.04,
        sub_hazard_per_min=0.02,
        sig_strikes_landed_per_min=4.0,
        takedown_attempts_per_min=0.6,
        takedown_accuracy=0.4,
        control_seconds_per_min=8.0,
    )
    base.update(kwargs)
    return UFCFighterTimelineProfile(**base)


class UFCTimelineTests(unittest.TestCase):
    def test_terminal_path_stops_and_decision_uses_full_clock(self):
        a = fighter("a", ko_hazard_per_min=0.8)
        b = fighter("b", ko_hazard_per_min=0.8)
        finishes = [simulate_fight_timeline(a, b, seed=seed) for seed in range(50)]
        self.assertTrue(any(path.outcome != "DECISION" for path in finishes))
        for path in finishes:
            self.assertLessEqual(path.elapsed_seconds, 900)
            if path.outcome != "DECISION":
                self.assertLess(path.elapsed_seconds, 900)

        decision = simulate_fight_timeline(
            fighter("c", ko_hazard_per_min=0, sub_hazard_per_min=0),
            fighter("d", ko_hazard_per_min=0, sub_hazard_per_min=0),
            seed=91,
        )
        self.assertEqual(decision.outcome, "DECISION")
        self.assertEqual(decision.elapsed_seconds, 900)

    def test_no_post_finish_accumulation_when_scheduled_rounds_change(self):
        a = fighter("a", ko_hazard_per_min=1.2)
        b = fighter("b", ko_hazard_per_min=0.01, sub_hazard_per_min=0.01)
        seed = next(
            seed
            for seed in range(1000)
            if simulate_fight_timeline(a, b, rounds=3, seed=seed).outcome != "DECISION"
        )
        p3 = simulate_fight_timeline(a, b, rounds=3, seed=seed)
        p5 = simulate_fight_timeline(a, b, rounds=5, seed=seed)
        self.assertEqual(p3, p5)

    def test_pairwise_style_is_opponent_specific(self):
        a = fighter("a", style_pressure=1.0)
        low_counter = fighter("b1", style_counter=-1.0)
        high_counter = fighter("b2", style_counter=1.0)
        self.assertGreater(
            pairwise_style_multipliers(a, low_counter)[0],
            pairwise_style_multipliers(a, high_counter)[0],
        )

    def test_offense_and_defense_cardio_decay_are_asymmetric(self):
        a_fresh = fighter("a1", offense_cardio_decay_per_round=0.0)
        a_tired = fighter("a2", offense_cardio_decay_per_round=0.4)
        b_stable = fighter("b1", defense_cardio_decay_per_round=0.0)
        b_tired = fighter("b2", defense_cardio_decay_per_round=0.4)
        fresh = effective_rates(a_fresh, b_stable, elapsed_seconds=600).sig_strikes_per_min
        offense_tired = effective_rates(a_tired, b_stable, elapsed_seconds=600).sig_strikes_per_min
        defense_tired = effective_rates(a_fresh, b_tired, elapsed_seconds=600).sig_strikes_per_min
        self.assertLess(offense_tired, fresh)
        self.assertGreater(defense_tired, fresh)

    def test_distribution_methods_and_win_probabilities_reconcile(self):
        a = fighter("a")
        b = fighter("b")
        out = simulate_fight_distribution(a, b, simulations=500, seed=33)
        self.assertAlmostEqual(out["a_win"] + out["b_win"], 1.0)
        self.assertAlmostEqual(
            out["a_ko_tko"] + out["a_submission"] + out["a_decision"],
            out["a_win"],
        )
        self.assertAlmostEqual(
            out["b_ko_tko"] + out["b_submission"] + out["b_decision"],
            out["b_win"],
        )
        self.assertAlmostEqual(out["a_decision"] + out["b_decision"], out["goes_distance"])

    def test_n_way_devig_is_not_pairwise(self):
        probs, hold = n_way_devig(
            {
                "a_ko": 180,
                "a_sub": 400,
                "a_dec": 250,
                "b_ko": 220,
                "b_sub": 500,
                "b_dec": 300,
            }
        )
        self.assertAlmostEqual(sum(probs.values()), 1.0)
        self.assertGreater(hold, 0.0)


if __name__ == "__main__":
    unittest.main()
