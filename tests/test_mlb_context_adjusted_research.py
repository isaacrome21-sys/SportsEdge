import unittest

from scripts.run_mlb_context_adjusted_research import _row_provenance
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

    def test_row_provenance_marks_weather_and_pitchers_incorporated(self):
        away = TeamRunProfile(1, 30, 4.6, 4.2)
        home = TeamRunProfile(2, 30, 4.4, 4.1)
        away_starter = StarterProfile(10, 12, 3.20, 18.0, "AVAILABLE")
        home_starter = StarterProfile(20, 12, 3.40, 17.5, "AVAILABLE")
        wx = weather_adjustment({"roof_type": "Open", "roof_state": "OPEN", "forecast": {"temperature": 87}})
        adjusted = context_adjusted_means(
            away=away,
            home=home,
            away_starter=away_starter,
            home_starter=home_starter,
            weather=wx,
        )
        context = {
            "source": "MLB_PUBLIC_PREGAME_BUNDLE",
            "status": "AVAILABLE",
            "as_of_utc": "2026-09-29T18:00:00+00:00",
            "payload_sha256": "bundle-sha",
            "weather_roof": {
                "source": "NWS_MLB_WEATHER_CONTEXT",
                "status": "AVAILABLE",
                "as_of_utc": "2026-09-29T18:00:00+00:00",
                "payload_sha256": "weather-sha",
                "roof_type": "Open",
                "roof_state": "OPEN",
                "forecast": {"temperature": 87},
                "forecast_hourly_url": "https://api.weather.gov/example/hourly",
            },
        }
        provenance = _row_provenance(
            context=context,
            game_pk=123,
            target_date="2026-09-29",
            context_as_of_utc="2026-09-29T18:00:00+00:00",
            away_pitcher={"player_id": 10, "player_name": "Away Starter"},
            home_pitcher={"player_id": 20, "player_name": "Home Starter"},
            adjusted=adjusted,
        )
        self.assertEqual(provenance["weather_roof"]["source"], "NWS_MLB_WEATHER_CONTEXT")
        self.assertTrue(provenance["weather_roof"]["incorporated"])
        self.assertEqual(provenance["weather_roof"]["status"], "incorporated")
        self.assertTrue(provenance["pitchers"]["away"]["incorporated"])
        self.assertTrue(provenance["pitchers"]["home"]["incorporated"])
        self.assertEqual(provenance["pitchers"]["away"]["history_source"], "MLB_STATSAPI_GAME_LOG_STRICTLY_PRIOR")
        self.assertEqual(provenance["pitchers"]["home"]["probable_pitcher_source"], "MLB_STATSAPI_LIVE_FEED")

    def test_row_provenance_never_displays_missing_source_as_incorporated(self):
        away = TeamRunProfile(1, 30, 4.2, 4.0)
        home = TeamRunProfile(2, 30, 4.1, 4.3)
        missing = StarterProfile(10, 0, None, None, "INSUFFICIENT_PRIOR_STARTS")
        wx = weather_adjustment({"roof_type": "Open", "forecast": {"temperature": 70}})
        adjusted = context_adjusted_means(
            away=away,
            home=home,
            away_starter=missing,
            home_starter=missing,
            weather=wx,
        )
        context = {
            "source": "MLB_PUBLIC_PREGAME_BUNDLE",
            "status": "PARTIAL",
            "payload_sha256": "bundle-sha",
            "weather_roof": {
                "source": "NWS_MLB_WEATHER_CONTEXT",
                "status": "UNAVAILABLE",
                "roof_type": "Open",
                "forecast": None,
            },
        }
        provenance = _row_provenance(
            context=context,
            game_pk=456,
            target_date="2026-09-29",
            context_as_of_utc="2026-09-29T18:00:00+00:00",
            away_pitcher={"player_id": 10, "player_name": "Away Starter"},
            home_pitcher={"player_id": 20, "player_name": "Home Starter"},
            adjusted=adjusted,
        )
        self.assertEqual(provenance["weather_roof"]["source"], "NOT_RETRIEVED")
        self.assertFalse(provenance["weather_roof"]["incorporated"])
        self.assertEqual(provenance["weather_roof"]["status"], "not incorporated")
        self.assertEqual(provenance["weather_roof"]["reason"], "WEATHER_ROOF_SOURCE_NOT_RETRIEVED")
        self.assertFalse(provenance["pitchers"]["away"]["incorporated"])
        self.assertEqual(provenance["pitchers"]["away"]["status"], "not incorporated")
        self.assertIn("INSUFFICIENT_PRIOR_STARTS", provenance["pitchers"]["away"]["reason"])


if __name__ == "__main__":
    unittest.main()