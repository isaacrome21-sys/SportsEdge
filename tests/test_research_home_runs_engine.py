import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.generic_market_engine import generic_market_engine_adapter
from sportsedge.research.home_runs_engine import (
    HomeRunsEngineError,
    compare_external_benchmark,
    fair_american_odds,
    simulate_home_runs,
)


class ResearchHomeRunsEngineTests(unittest.TestCase):
    def _input(self, **feature_overrides):
        features = {
            "batter_hr_rate": 0.050,
            "pitcher_hr_rate_allowed": 0.040,
            "league_hr_rate": 0.033,
            "park_hr_factor": 1.00,
            "barrel_rate": 0.12,
            "hard_hit_rate": 0.45,
            "avg_exit_velocity": 90.5,
            "pa_pool": [4, 4, 5, 5],
        }
        features.update(feature_overrides)
        return {
            "build_hash": "a" * 64,
            "market": "home_runs",
            "lineup_status": "CONFIRMED",
            "require_confirmed_lineup": True,
            "features": features,
        }

    def test_home_run_probability_is_between_zero_and_one(self):
        out = simulate_home_runs(self._input())
        self.assertGreater(out.probs[0.5], 0.0)
        self.assertLess(out.probs[0.5], 1.0)
        self.assertGreater(out.expected_home_runs, 0.0)
        self.assertAlmostEqual(out.probs[0.5], out.haircut_home_run_probability, places=12)

    def test_more_hitter_power_increases_home_run_probability(self):
        low = simulate_home_runs(self._input(batter_hr_rate=0.025)).probs[0.5]
        high = simulate_home_runs(self._input(batter_hr_rate=0.080)).probs[0.5]
        self.assertGreater(high, low)

    def test_more_pitcher_hr_allowed_increases_home_run_probability(self):
        low = simulate_home_runs(self._input(pitcher_hr_rate_allowed=0.020)).probs[0.5]
        high = simulate_home_runs(self._input(pitcher_hr_rate_allowed=0.070)).probs[0.5]
        self.assertGreater(high, low)

    def test_more_homer_friendly_park_increases_probability(self):
        low = simulate_home_runs(self._input(park_hr_factor=0.80)).probs[0.5]
        high = simulate_home_runs(self._input(park_hr_factor=1.30)).probs[0.5]
        self.assertGreater(high, low)

    def test_sportsbook_derived_feature_fails_closed(self):
        model_input = self._input()
        model_input["features"]["sportsbook_prob"] = 0.25
        with self.assertRaises(HomeRunsEngineError):
            simulate_home_runs(model_input)

    def test_external_model_probability_fails_closed_inside_model_features(self):
        model_input = self._input()
        model_input["features"]["ballparkpal_probability"] = 0.25
        with self.assertRaises(HomeRunsEngineError):
            simulate_home_runs(model_input)

    def test_recent_contact_surge_is_haircut_toward_stable_baseline(self):
        out = simulate_home_runs(self._input(
            recent_hard_hit_rate=0.62,
            recent_barrel_rate=0.20,
            recent_avg_exit_velocity=96.0,
            recent_batted_balls=20,
        ))
        self.assertGreater(out.raw_home_run_probability, out.baseline_home_run_probability)
        self.assertGreater(out.haircut_home_run_probability, out.baseline_home_run_probability)
        self.assertLess(out.haircut_home_run_probability, out.raw_home_run_probability)
        self.assertGreater(out.contact_signal, 0.0)
        self.assertGreater(out.contact_reliability, 0.0)
        self.assertLess(out.contact_reliability, 1.0)

    def test_larger_recent_sample_reduces_haircut_distance(self):
        small = simulate_home_runs(self._input(
            recent_hard_hit_rate=0.62,
            recent_barrel_rate=0.20,
            recent_avg_exit_velocity=96.0,
            recent_batted_balls=10,
        ))
        large = simulate_home_runs(self._input(
            recent_hard_hit_rate=0.62,
            recent_barrel_rate=0.20,
            recent_avg_exit_velocity=96.0,
            recent_batted_balls=100,
        ))
        small_gap = small.raw_home_run_probability - small.haircut_home_run_probability
        large_gap = large.raw_home_run_probability - large.haircut_home_run_probability
        self.assertLess(large_gap, small_gap)

    def test_partial_recent_contact_group_fails_closed(self):
        with self.assertRaises(HomeRunsEngineError):
            simulate_home_runs(self._input(
                recent_hard_hit_rate=0.60,
                recent_batted_balls=20,
            ))

    def test_optional_sample_shrinkage_moves_extreme_rate_toward_league(self):
        unshrunk = simulate_home_runs(self._input(batter_hr_rate=0.12))
        shrunk = simulate_home_runs(self._input(batter_hr_rate=0.12, batter_pa_sample=20))
        self.assertLess(shrunk.baseline_home_run_probability, unshrunk.baseline_home_run_probability)

    def test_uncle_mal_screenshot_arithmetic_reconstructs_bpp_denominator(self):
        # 9/3/26 screenshot: displayed raw probability divided by displayed model/BPP
        # ratio reproduces the displayed "haircut P" to rounding. This test captures
        # the observable arithmetic only; it does not claim the proprietary formula.
        rows = [
            (0.368, 0.249, 1.48),
            (0.327, 0.252, 1.30),
            (0.301, 0.264, 1.14),
        ]
        for raw_p, bpp_p, displayed_ratio in rows:
            comp = compare_external_benchmark(raw_p, bpp_p, benchmark_name="BPP")
            self.assertAlmostEqual(comp.model_to_benchmark_ratio, displayed_ratio, delta=0.01)

    def test_uncle_mal_screenshot_fair_odds_match_probability(self):
        self.assertAlmostEqual(fair_american_odds(0.368), 172.0, delta=0.5)
        self.assertAlmostEqual(fair_american_odds(0.327), 206.0, delta=0.5)
        self.assertAlmostEqual(fair_american_odds(0.301), 232.0, delta=0.5)

    def test_research_engine_is_not_canonical_runtime(self):
        adapter = engine_registry()["HOME_RUNS"]
        self.assertIs(adapter, generic_market_engine_adapter)
        out = adapter({
            "market": "HOME_RUNS", "game_id": "1", "entity_id": "2",
            "line": 0.5, "side": "OVER", "expected_count": 0.22,
            "feature_source_hash": "f" * 64,
        })
        self.assertEqual(out["engine_version"], "mlb_full_market_runtime_v2")


if __name__ == "__main__":
    unittest.main()
