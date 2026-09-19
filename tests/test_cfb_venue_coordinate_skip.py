from __future__ import annotations

import unittest

from scripts.acquire_cfb_reconstructed_selection import (
    _try_venue_coordinates,
    _venue_indexes,
    _resolve_venue,
)


class TestCFBVenueCoordinateSkip(unittest.TestCase):
    def test_skips_venues_without_coordinates_instead_of_aborting(self):
        rows = [
            {"id": 1, "name": "Good Stadium", "dome": False, "latitude": 41.88, "longitude": -87.62},
            {"id": 2, "name": "Broken Stadium", "dome": False},
            {"id": 3, "name": "Nested Stadium", "dome": True, "location": {"latitude": 33.44, "longitude": -112.07}},
        ]
        by_id, by_name = _venue_indexes(rows)
        self.assertIn("1", by_id)
        self.assertIn("3", by_id)
        self.assertNotIn("2", by_id)
        self.assertIsNone(_try_venue_coordinates(rows[1]))
        self.assertIsNone(_resolve_venue({"venueId": 2, "venue": "Broken Stadium"}, by_id=by_id, by_name=by_name))
        self.assertEqual(_resolve_venue({"venueId": 1}, by_id=by_id, by_name=by_name)["name"], "Good Stadium")


if __name__ == "__main__":
    unittest.main()
