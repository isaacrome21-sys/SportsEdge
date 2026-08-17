import unittest

from sportsedge.engine_registry import engine_registry
from sportsedge.home_runs_engine import HomeRunsEngineError, simulate_home_runs


class HomeRunsEngineTests(unittest.TestCase):
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

    def test_registry_uses_dedicated_home_run_adapter(self):
        adapter = engine_registry()["HOME_RUNS"]
        model_input = self._input()
        model_input.update({
            "market": "HOME_RUNS", "game_id": "1", "entity_id": "2",
            "line": 0.5, "side": "OVER",
        })
        out = adapter(model_input)
        self.assertEqual(out["market"], "HOME_RUNS")
        self.assertTrue(out["engine_version"].startswith("home_runs_research_"))
        self.assertGreater(out["model_p"], 0.0)
        self.assertLess(out["model_p"], 1.0)


if __name__ == "__main__":
    unittest.main()
