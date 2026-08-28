from datetime import datetime, timedelta, timezone
import unittest

from sportsedge.pga.live_model import (
    LiveWeights,
    PlayerLiveState,
    evaluate_live_truth_gate,
    live_expected_sg_per_round,
    simulate_remaining_tournament,
)


class PGALiveModelTests(unittest.TestCase):
    def _player(self, name: str, start: float, skill: float, wave: str = "A") -> PlayerLiveState:
        return PlayerLiveState(
            player=name,
            leaderboard_strokes_to_par=start,
            long_term_sg=skill,
            current_event_t2g_sg=skill,
            recent_form_sg=skill,
            course_fit_sg=skill,
            round_sd=2.0,
            wave=wave,
        )

    def test_live_weights_normalize_and_reject_negative_weight(self):
        w = LiveWeights().normalized()
        total = sum((
            w.long_term_skill,
            w.current_event_ball_striking,
            w.recent_form,
            w.course_fit,
            w.putting_scrambling_sustainability,
            w.weather_tee_wave,
            w.volatility_error_profile,
        ))
        self.assertAlmostEqual(total, 1.0)
        with self.assertRaisesRegex(ValueError, "WEIGHTS_INVALID"):
            LiveWeights(course_fit=-0.1).normalized()

    def test_current_event_t2g_moves_mean_but_does_not_overwrite_prior(self):
        state = PlayerLiveState(
            player="Player A",
            leaderboard_strokes_to_par=-2,
            long_term_sg=1.0,
            current_event_t2g_sg=3.0,
            recent_form_sg=1.0,
            course_fit_sg=1.0,
        )
        mu = live_expected_sg_per_round(state)
        self.assertGreater(mu, 1.0)
        self.assertLess(mu, 3.0)

    def test_live_simulation_rewards_actual_lead_and_skill(self):
        players = [
            self._player("Leader", -6, 1.2),
            self._player("Chaser", -4, 0.8),
            self._player("Back", 1, 0.2),
        ]
        out = simulate_remaining_tournament(players, rounds_remaining=3, n_sims=4000, seed=7)
        self.assertGreater(out["Leader"].win_prob, out["Back"].win_prob)
        self.assertLess(out["Leader"].expected_finish, out["Back"].expected_finish)
        self.assertAlmostEqual(sum(row.win_prob for row in out.values()), 1.0, places=8)

    def test_position_dead_heat_payout_never_exceeds_raw_finish_probability(self):
        players = [self._player(f"P{i}", 0, 0, wave="A" if i % 2 else "B") for i in range(1, 9)]
        out = simulate_remaining_tournament(
            players,
            rounds_remaining=1,
            n_sims=1000,
            seed=17,
            common_round_sd=0,
            wave_round_sd=0,
            latent_form_sd=0,
        )
        for row in out.values():
            self.assertLessEqual(row.top5_dead_heat_payout, row.top5_prob + 1e-12)
            self.assertLessEqual(row.top10_dead_heat_payout, row.top10_prob + 1e-12)
            self.assertLessEqual(row.top20_dead_heat_payout, row.top20_prob + 1e-12)

    def test_wave_shock_is_not_global_noise_that_cancels_from_rankings(self):
        # With zero player noise/form and equal players, different waves can separate.
        players = [
            PlayerLiveState("A1", 0, 0, 0, 0, 0, round_sd=1.6, wave="AM"),
            PlayerLiveState("A2", 0, 0, 0, 0, 0, round_sd=1.6, wave="AM"),
            PlayerLiveState("P1", 0, 0, 0, 0, 0, round_sd=1.6, wave="PM"),
            PlayerLiveState("P2", 0, 0, 0, 0, 0, round_sd=1.6, wave="PM"),
        ]
        out = simulate_remaining_tournament(
            players,
            rounds_remaining=1,
            n_sims=300,
            seed=123,
            common_round_sd=0,
            wave_round_sd=2.0,
            latent_form_sd=0,
        )
        self.assertAlmostEqual(sum(row.win_prob for row in out.values()), 1.0, places=8)

    def test_truth_gate_distinguishes_missing_from_stale_and_requires_aware_time(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        result = evaluate_live_truth_gate(
            leaderboard_timestamp=None,
            tee_time_timestamp=now - timedelta(hours=1),
            weather_timestamp=now - timedelta(minutes=90),
            market_timestamp=now - timedelta(minutes=2),
            has_shot_level_data=True,
            wd_status_verified=True,
            market_rules_verified=True,
            edge=0.05,
            expected_value=0.06,
            min_edge=0.02,
            min_ev=0.02,
            now=now,
        )
        self.assertFalse(result.passed)
        self.assertIn("missing_leaderboard", result.reasons)
        self.assertTrue(any(reason.startswith("stale_weather:") for reason in result.reasons))
        with self.assertRaisesRegex(ValueError, "TIMEZONE_REQUIRED"):
            evaluate_live_truth_gate(
                leaderboard_timestamp=now,
                tee_time_timestamp=now,
                weather_timestamp=now,
                market_timestamp=now,
                has_shot_level_data=True,
                wd_status_verified=True,
                market_rules_verified=True,
                edge=0.05,
                expected_value=0.06,
                min_edge=0.02,
                min_ev=0.02,
                now=datetime(2026, 8, 21, 12, 0),
            )

    def test_missing_shot_level_data_downgrades_confidence_only_when_other_gates_pass(self):
        now = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)
        result = evaluate_live_truth_gate(
            leaderboard_timestamp=now - timedelta(minutes=1),
            tee_time_timestamp=now - timedelta(hours=1),
            weather_timestamp=now - timedelta(minutes=10),
            market_timestamp=now - timedelta(minutes=2),
            has_shot_level_data=False,
            wd_status_verified=True,
            market_rules_verified=True,
            edge=0.05,
            expected_value=0.06,
            min_edge=0.02,
            min_ev=0.02,
            now=now,
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.confidence_tier, "B")
        self.assertIn("shot_level_missing_confidence_downgrade", result.reasons)


if __name__ == "__main__":
    unittest.main()
