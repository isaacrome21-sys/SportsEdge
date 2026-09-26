from __future__ import annotations

import unittest

from scripts.acquire_cfb_reconstructed_selection import _resolve_venue


class TestAcquireNullWeatherVenueSkip(unittest.TestCase):
    def test_resolve_venue_returns_none_when_unresolved(self):
        by_id = {
            "10": {
                "venue_id": "10",
                "name": "Camp Randall",
                "dome": False,
                "latitude": 43.07,
                "longitude": -89.41,
            }
        }
        by_name = {"camp randall": by_id["10"]}
        self.assertIsNotNone(_resolve_venue({"venueId": 10, "venue": "Camp Randall"}, by_id=by_id, by_name=by_name))
        self.assertIsNone(_resolve_venue({"id": 999, "venueId": 99, "venue": "Unknown Field"}, by_id=by_id, by_name=by_name))


if __name__ == "__main__":
    unittest.main()
