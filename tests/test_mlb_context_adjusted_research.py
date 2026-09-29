import unittest

from sportsedge.mlb_context_adjusted_research import (
    StarterProfile,
    TeamRunProfile,
    context_adjusted_means,
    weather_adjustment,
)


class TestMLBContextAdjustedResearch(unittest.TestCase):
    def test_retractable_unknown_weather_fails_neutral(self):
        out = weather_adjustment({
            "roof_type": "Retractable",
            "roof_state": "UNKNOWN",
            "forecast": {"temperature": 91},
        })
        self.assertFalse(out.applied)
        self.assertEqual(out.multiplier, 1.0)
        self.assertIn("RETRACTABLE_ROOF", out.reason)

    def test_open_average_weather_is_consumed_but_neutral(self):
        out = weather_adjustment({
            "roof_type": "Open",
            "roof_state": "UNKNOWN",
            "forecast": {"temperature": 73},
        })
        self.assertTrue(out.applied)
        self.assertEqual(out.multiplier, 1.0)
        self.assertEqual(out.reason, "AVERAGE_TEMPERATURE_BIN_NEUTRAL")

    def test_open_warm_weather_changes_research_multiplier(self):
        out = weather_adjustment({
            "roof_type": "Open",
            "forecast": {"temperature": 90},
        })
        self.assertTrue(out.applied)
        self.assertGreater(out.multiplier, 1.0)

    def test_strong_starter_reduces_opponent_mean(self):
        away = TeamRunProfile(1, 30, 5.0, 4.5)
        home = TeamRunProfile(2, 30, 4.5, 4.6)
        strong_home = StarterProfile(20, 12, 2.0, 18.0, "AVAILABLE")
        neutral_away = StarterProfile(10, 0, None, None, "INSUFFICIENT_PRIOR_STARTS")
        wx = weather_adjustment({"roof_type": "Open", "forecast": {"temperature": 70}})
        result = context_adjusted_means(
            away=away,
            home=home,
            away_starter=neutral_away,
            home_starter=strong_home,
            weather=wx,
        )
        pre = result["components"]["away_pre_starter_mean"]
        self.assertLess(result["away_mean_runs"], pre)
        self.assertEqual(result["label"], "NOT_MODEL_P")
        self.assertFalse(result["model_p_eligible"])
        self.assertFalse(result["promotion_evidence"])

    def test_missing_starter_is_neutral_not_invented(self):
        away = TeamRunProfile(1, 30, 4.2, 4.0)
        home = TeamRunProfile(2, 30, 4.1, 4.3)
        missing = StarterProfile(10, 0, None, None, "INSUFFICIENT_PRIOR_STARTS")
        wx = weather_adjustment({"roof_type": "Open", "forecast": {"temperature": 70}})
        result = context_adjusted_means(
            away=away,
            home=home,
            away_starter=missing,
            home_starter=missing,
            weather=wx,
        )
        self.assertAlmostEqual(result["away_mean_runs"], 0.5 * 4.2 + 0.5 * 4.3)
        self.assertAlmostEqual(result["home_mean_runs"], 0.5 * 4.1 + 0.5 * 4.0)


if __name__ == "__main__":
    unittest.main()
