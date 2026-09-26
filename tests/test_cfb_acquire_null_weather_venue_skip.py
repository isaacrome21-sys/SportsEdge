from __future__ import annotations

import unittest

from scripts.acquire_cfb_reconstructed_selection import _resolve_venue
from sportsedge.sports.cfb.reconstructed_acquire_weather import resolve_venue


class TestAcquireNullWeatherVenueSkip(unittest.TestCase):
    def setUp(self):
        self.by_id = {
            "10": {
                "venue_id": "10",
                "name": "Camp Randall",
                "dome": False,
                "latitude": 43.07,
                "longitude": -89.41,
            }
        }
        self.by_name = {"camp randall": self.by_id["10"]}

    def test_helper_resolve_venue_returns_none_when_unresolved(self):
        self.assertIsNotNone(
            resolve_venue({"venueId": 10, "venue": "Camp Randall"}, by_id=self.by_id, by_name=self.by_name)
        )
        self.assertIsNone(
            resolve_venue({"id": 999, "venueId": 99, "venue": "Unknown Field"}, by_id=self.by_id, by_name=self.by_name)
        )

    def test_acquire_resolve_venue_delegates_to_helper(self):
        self.assertIsNotNone(
            _resolve_venue({"venueId": 10, "venue": "Camp Randall"}, by_id=self.by_id, by_name=self.by_name)
        )
        self.assertIsNone(
            _resolve_venue({"id": 999, "venueId": 99, "venue": "Unknown Field"}, by_id=self.by_id, by_name=self.by_name)
        )


if __name__ == "__main__":
    unittest.main()
