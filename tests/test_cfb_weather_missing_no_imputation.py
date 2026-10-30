from __future__ import annotations

import unittest

from sportsedge.sports.cfb.reconstructed_selection import (
    CFBReconstructedSelectionError,
    _weather,
    WEATHER_MISSING_SOURCE,
)
from sportsedge.sports.cfb.source import CFBGame
from sportsedge.sports.cfb.reconstructed_acquire_weather import resolve_venue


class TestWeatherMissingNoImputation(unittest.TestCase):
    """WEATHER_MISSING is enforced outside V3-bound joint_model.py.

    joint_model.py blob ff91ad867a5240d7f1cd90c707d29d534bde8dd2 is frozen in
    cfb_candidate_bakeoff_evaluator_v3.json and must not change.
    """

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

    def test_reconstructed_weather_rejects_null_indoor_without_missing_flag(self):
        game = CFBGame(
            game_id="g2", season=2020, week=3, start_ts="2020-09-12T16:00:00+00:00",
            home_team="A", away_team="B", neutral_site=False, venue=None,
        )
        with self.assertRaises(CFBReconstructedSelectionError) as ctx:
            _weather(game, {
                "source": "SOME_OTHER_SOURCE",
                "retrieved_at_utc": "2020-09-12T12:00:00+00:00",
                "gameIndoors": None,
                "windSpeed": None,
                "temperature": None,
            })
        self.assertIn("WEATHER_INDOOR_INVALID", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
