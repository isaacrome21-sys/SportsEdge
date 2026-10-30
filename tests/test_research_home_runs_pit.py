import unittest

from sportsedge.research.home_runs_pit import HomeRunsPITError, build_home_runs_pit_model_row


def model_input():
    return {
        "market": "home_runs",
        "build_hash": "frozen-v02-test",
        "lineup_status": "CONFIRMED",
        "features": {
            "batter_hr_rate": 0.055,
            "pitcher_hr_rate_allowed": 0.045,
            "league_hr_rate": 0.032,
            "park_hr_factor": 1.05,
            "barrel_rate": 0.11,
            "hard_hit_rate": 0.44,
            "avg_exit_velocity": 90.2,
            "pa_pool": [4, 4, 5],
            "batter_pa_sample": 420,
            "pitcher_pa_sample": 500,
            "recent_hard_hit_rate": 0.54,
            "recent_barrel_rate": 0.15,
            "recent_avg_exit_velocity": 93.1,
            "recent_batted_balls": 35,
        },
    }


class HomeRunsPITTests(unittest.TestCase):
    def _row(self, **overrides):
        kwargs = dict(
            game_id="2026-09-04-AAA-BBB",
            entity_id="12345",
            line=0.5,
            side="OVER",
            quote_ts="2026-09-04T22:00:00+00:00",
            first_pitch_ts="2026-09-04T23:05:00+00:00",
            history_asof_ts="2026-09-04T21:55:00+00:00",
            history_source_hash="a" * 64,
            model_input=model_input(),
            evidence_class="SYNTHETIC_CONTRACT_TEST",
        )
        kwargs.update(overrides)
        return build_home_runs_pit_model_row(**kwargs)

    def test_row_maps_frozen_v02_to_candidate_and_baseline_to_incumbent(self):
        row = self._row()
        self.assertEqual(row["market"], "HOME_RUNS")
        self.assertEqual(row["candidate_model"], "SURGE_HAIRCUT_V02")
        self.assertEqual(row["incumbent_model"], "STABLE_BASELINE_V01")
        self.assertAlmostEqual(row["candidate_p"], row["candidate_over_probability"])
        self.assertAlmostEqual(row["incumbent_p"], row["incumbent_over_probability"])
        self.assertEqual(len(row["model_input_hash"]), 64)
        self.assertEqual(len(row["model_row_sha256"]), 64)

    def test_under_is_exact_complement_of_over_probabilities(self):
        over = self._row(side="OVER")
        under = self._row(side="UNDER")
        self.assertAlmostEqual(over["candidate_p"] + under["candidate_p"], 1.0)
        self.assertAlmostEqual(over["incumbent_p"] + under["incumbent_p"], 1.0)

    def test_post_quote_or_post_first_pitch_history_fails_closed(self):
        with self.assertRaisesRegex(HomeRunsPITError, "timestamp order"):
            self._row(history_asof_ts="2026-09-04T22:01:00+00:00")
        with self.assertRaisesRegex(HomeRunsPITError, "timestamp order"):
            self._row(quote_ts="2026-09-04T23:06:00+00:00")

    def test_market_or_external_model_contamination_fails_closed(self):
        contaminated = model_input()
        contaminated["features"] = dict(contaminated["features"])
        contaminated["features"]["american_odds"] = 350
        with self.assertRaisesRegex(HomeRunsPITError, "prohibited"):
            self._row(model_input=contaminated)

    def test_only_standard_anytime_hr_line_is_allowed(self):
        with self.assertRaisesRegex(HomeRunsPITError, "only line 0.5"):
            self._row(line=1.5)


if __name__ == "__main__":
    unittest.main()
