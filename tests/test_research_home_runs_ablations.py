import unittest

from sportsedge.research.home_runs_ablations import (
    GEOMETRY_ARM,
    PARK_WEATHER_ARM,
    PLATOON_ARM,
    evaluate_isolated_v03_arms,
    geometry_v03,
    park_weather_v03,
    platoon_v03,
)
from sportsedge.research.home_runs_evaluation import evaluate_home_run_arms


class HomeRunsAblationTests(unittest.TestCase):
    def setUp(self):
        self.base = 0.25
        self.pa_pool = [4, 4, 5]

    def test_neutral_family_inputs_are_noops(self):
        platoon = platoon_v03(
            base_probability=self.base,
            pa_pool=self.pa_pool,
            batter_hr_rate_vs_hand=0.05,
            batter_hr_rate_overall=0.05,
            batter_split_pa=200,
            pitcher_hr_rate_allowed_vs_hand=0.04,
            pitcher_hr_rate_allowed_overall=0.04,
            pitcher_split_pa=250,
        )
        park = park_weather_v03(
            base_probability=self.base,
            pa_pool=self.pa_pool,
            generic_park_hr_factor=1.0,
            handed_park_hr_factor=1.0,
            weather_hr_multiplier=1.0,
        )
        geometry = geometry_v03(
            base_probability=self.base,
            pa_pool=self.pa_pool,
            pull_share=0.40,
            center_share=0.35,
            oppo_share=0.25,
            pull_park_hr_factor=1.0,
            center_park_hr_factor=1.0,
            oppo_park_hr_factor=1.0,
            directional_bbe=150,
        )
        for output in (platoon, park, geometry):
            self.assertAlmostEqual(output.probability, self.base, places=10)

    def test_isolated_runner_never_compounds_arms(self):
        outputs = evaluate_isolated_v03_arms(
            base_probability=self.base,
            pa_pool=self.pa_pool,
            platoon={
                "batter_hr_rate_vs_hand": 0.07,
                "batter_hr_rate_overall": 0.05,
                "batter_split_pa": 200,
                "pitcher_hr_rate_allowed_vs_hand": 0.05,
                "pitcher_hr_rate_allowed_overall": 0.04,
                "pitcher_split_pa": 250,
            },
            park_weather={
                "generic_park_hr_factor": 1.0,
                "handed_park_hr_factor": 1.10,
                "weather_hr_multiplier": 1.05,
            },
            geometry={
                "pull_share": 0.50,
                "center_share": 0.30,
                "oppo_share": 0.20,
                "pull_park_hr_factor": 1.20,
                "center_park_hr_factor": 0.95,
                "oppo_park_hr_factor": 0.90,
                "directional_bbe": 180,
            },
        )
        self.assertEqual(set(outputs), {PLATOON_ARM, PARK_WEATHER_ARM, GEOMETRY_ARM})
        self.assertTrue(all(abs(out.base_probability - self.base) < 1e-12 for out in outputs.values()))
        self.assertTrue(all(out.probability > self.base for out in outputs.values()))

    def test_chronological_evaluation_uses_paired_common_rows(self):
        rows = []
        for i in range(20):
            y = 1 if i % 2 == 0 else 0
            rows.append({
                "game_date": "2026-09-%02d" % (1 + i),
                "outcome": y,
                "baseline_v01": 0.50,
                "surge_haircut_v02": 0.55 if y else 0.45,
                "platoon_v03": 0.80 if y else 0.20,
                "park_weather_v03": 0.60 if y else 0.40,
                "geometry_v03": None if i < 5 else (0.65 if y else 0.35),
            })
        report = evaluate_home_run_arms(rows, calibration_bins=5)
        platoon_delta = report["paired_deltas"]["platoon_v03_vs_surge_haircut_v02"]
        geometry_delta = report["paired_deltas"]["geometry_v03_vs_surge_haircut_v02"]
        self.assertEqual(platoon_delta["n"], 20)
        self.assertEqual(geometry_delta["n"], 15)
        self.assertLess(platoon_delta["brier_delta"], 0)
        self.assertLess(platoon_delta["log_loss_delta"], 0)
        self.assertFalse(report["interpretation"]["random_shuffle_used"])
        self.assertEqual(list(report["chronological_months"]), ["2026-09"])


if __name__ == "__main__":
    unittest.main()
