import unittest
from random import Random

from sportsedge.pga_engine import (
    PGAPlayer,
    PGATournamentConfig,
    _sample_round_delta,
    american_implied,
    dead_heat_expected_value,
    dead_heat_payout_fraction,
    n_way_devig,
    regularized_course_adjustment,
    simulate_head_to_head_probabilities,
    simulate_one_tournament,
    simulate_tournament_market_probabilities,
)
from sportsedge.truth_gate import TruthGateError


class PGAEngineTests(unittest.TestCase):
    def test_course_fit_is_heavily_regularized(self):
        player = PGAPlayer("1", "A", 0.0, 0.0, course_fit=99.0, blowup_rate=0.0)
        self.assertAlmostEqual(regularized_course_adjustment(player, PGATournamentConfig()), 0.30)

    def test_dead_heat_boundary_splits_paid_slots(self):
        scores = [270, 271, 272, 272, 272, 275]
        self.assertEqual(dead_heat_payout_fraction(scores, 272, 3), 1 / 3)
        self.assertEqual(dead_heat_payout_fraction(scores, 272, 5), 1.0)

    def test_dead_heat_expected_value_prices_paid_fraction_not_raw_top_k_hit(self):
        # At +400, a 25% expected paid fraction returns 0.25 * 5 = 1.25.
        self.assertAlmostEqual(dead_heat_expected_value(0.25, 400), 0.25)

    def test_pga_odds_validation_uses_canonical_sportsedge_contract(self):
        self.assertAlmostEqual(american_implied(200), 1 / 3)
        with self.assertRaises(TruthGateError):
            american_implied(50)
        with self.assertRaises(TruthGateError):
            american_implied(True)

    def test_n_way_devig_normalizes_entire_market_and_reports_hold(self):
        probs, hold = n_way_devig({"a": 200, "b": 250, "c": 300, "d": 350})
        self.assertAlmostEqual(sum(probs.values()), 1.0)
        self.assertGreater(hold, 0.0)

    def test_same_wave_weather_is_shared_not_player_independent(self):
        config = PGATournamentConfig(
            cut_top_n=3,
            wave_weather_sigma=3.0,
            common_weather_sigma=0.0,
            tournament_form_sigma=0.0,
        )
        players = [
            PGAPlayer("1", "A1", 0, 0, wave="AM", blowup_rate=0),
            PGAPlayer("2", "A2", 0, 0, wave="AM", blowup_rate=0),
            PGAPlayer("3", "P1", 0, 0, wave="PM", blowup_rate=0),
        ]
        path = simulate_one_tournament(players, config=config, seed=7)
        a1, a2, p1 = path.players
        self.assertEqual(a1.round_scores, a2.round_scores)
        self.assertTrue(any(x != y for x, y in zip(a1.round_scores, p1.round_scores)))

    def test_cut_line_is_top_n_and_ties(self):
        config = PGATournamentConfig(
            cut_top_n=2,
            wave_weather_sigma=0,
            common_weather_sigma=0,
            tournament_form_sigma=0,
        )
        players = [
            PGAPlayer("1", "Elite", 3, 0, blowup_rate=0),
            PGAPlayer("2", "TieA", 1, 0, blowup_rate=0),
            PGAPlayer("3", "TieB", 1, 0, blowup_rate=0),
            PGAPlayer("4", "Bad", -3, 0, blowup_rate=0),
        ]
        path = simulate_one_tournament(players, config=config, seed=1)
        cut_scores = sorted(row.cut_score for row in path.players)
        self.assertEqual(path.cut_line, cut_scores[1])
        self.assertEqual(sum(row.made_cut for row in path.players), 3)

    def test_bad_score_tail_is_fatter_than_central_draw(self):
        player = PGAPlayer("1", "Tail", 0, 1, blowup_rate=0.20, right_tail_scale=3.0)
        rng = Random(123)
        draws = sorted(_sample_round_delta(rng, player, 0.0) for _ in range(10000))
        self.assertGreater(draws[9499], abs(draws[5000]))

    def test_market_outputs_include_outright_frl_cut_and_joint_position_readouts(self):
        config = PGATournamentConfig(cut_top_n=3, wave_weather_sigma=0.5)
        players = [
            PGAPlayer(str(i), f"P{i}", (4 - i) * 0.4, 0.8, wave="A" if i % 2 else "B")
            for i in range(1, 6)
        ]
        out = simulate_tournament_market_probabilities(
            players,
            config=config,
            simulations=300,
            seed=99,
            position_k=(2, 3),
        )
        self.assertAlmostEqual(sum(row["outright_win_share"] for row in out.values()), 1.0)
        self.assertAlmostEqual(sum(row["first_round_leader_share"] for row in out.values()), 1.0)
        for row in out.values():
            self.assertLessEqual(row["top_2_dead_heat_payout"], row["top_2_probability"])
            self.assertLessEqual(row["top_2_probability"], row["top_3_probability"])
            self.assertGreaterEqual(row["make_cut_probability"], 0.0)
            self.assertLessEqual(row["make_cut_probability"], 1.0)

    def test_h2h_uses_joint_tournament_and_models_pushes(self):
        config = PGATournamentConfig(
            cut_top_n=3,
            wave_weather_sigma=0,
            common_weather_sigma=0,
            tournament_form_sigma=0,
        )
        players = [
            PGAPlayer("a", "A", 2, 0, blowup_rate=0),
            PGAPlayer("b", "B", 0, 0, blowup_rate=0),
            PGAPlayer("c", "C", -2, 0, blowup_rate=0),
        ]
        out = simulate_head_to_head_probabilities(
            players,
            [("a", "b"), ("b", "c")],
            config=config,
            simulations=20,
            seed=12,
        )
        self.assertEqual(out[("a", "b")]["a_win"], 1.0)
        self.assertEqual(out[("b", "c")]["a_win"], 1.0)
        for row in out.values():
            self.assertAlmostEqual(sum(row.values()), 1.0)

    def test_seeded_simulation_is_replayable(self):
        players = [
            PGAPlayer("a", "A", 1.0, 1.0),
            PGAPlayer("b", "B", 0.0, 1.0),
            PGAPlayer("c", "C", -1.0, 1.0),
        ]
        first = simulate_tournament_market_probabilities(players, simulations=50, seed=441)
        second = simulate_tournament_market_probabilities(players, simulations=50, seed=441)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
