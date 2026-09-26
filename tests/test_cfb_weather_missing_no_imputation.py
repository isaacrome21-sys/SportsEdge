from __future__ import annotations

import unittest

from sportsedge.sports.cfb.joint_model import CFBModelError, _feature_vector
from sportsedge.sports.cfb.reconstructed_selection import _weather
from sportsedge.sports.cfb.source import CFBGame
from sportsedge.sports.cfb.reconstructed_acquire_weather import resolve_venue, WEATHER_MISSING_SOURCE


def _metrics():
    keys = (
        "off_ppa_rush", "off_ppa_dropback", "def_ppa_rush_allowed", "def_ppa_dropback_allowed",
        "off_success_rate", "def_success_rate_allowed", "standard_down_ppa",
        "passing_down_success_rate", "eckel_rate", "points_per_eckel", "points_per_drive",
        "net_field_position", "explosive_rate",
    )
    return {k: 0.1 for k in keys}


class TestWeatherMissingNoImputation(unittest.TestCase):
    def test_resolve_venue_none(self):
        self.assertIsNone(resolve_venue({"id": 1, "venueId": 99, "venue": "X"}, by_id={}, by_name={}))

    def test_reconstructed_weather_preserves_none(self):
        game = CFBGame(
            game_id="g1", season=2020, week=3, start_ts="2020-09-12T16:00:00+00:00",
            home_team="A", away_team="B", neutral_site=False, venue=None,
        )
        out = _weather(game, {
            "source": WEATHER_MISSING_SOURCE,
            "retrieved_at_utc": "2020-09-12T12:00:00+00:00",
            "gameIndoors": None,
            "windSpeed": None,
            "temperature": None,
            "weather_missing": True,
        })
        self.assertIsNone(out["gameIndoors"])
        self.assertIsNone(out["windSpeed"])
        self.assertIsNone(out["temperature"])
        self.assertTrue(out["weather_missing"])
        self.assertEqual(out["source"], WEATHER_MISSING_SOURCE)

    def test_joint_model_refuses_missing_weather_imputation(self):
        row = {
            "neutral_site": False,
            "home_metrics": _metrics(),
            "away_metrics": _metrics(),
            "weather": {
                "source": WEATHER_MISSING_SOURCE,
                "weather_missing": True,
                "gameIndoors": None,
                "windSpeed": None,
                "temperature": None,
            },
        }
        with self.assertRaises(CFBModelError) as ctx:
            _feature_vector(row)
        self.assertIn("WEATHER_MISSING", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
