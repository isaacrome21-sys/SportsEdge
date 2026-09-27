from __future__ import annotations

import unittest

from sportsedge.sports.cfb.venue_coordinates import try_venue_coordinates, venue_indexes


class TestCFBVenueCoordinateSkip(unittest.TestCase):
    def test_skips_venues_without_coordinates_instead_of_aborting(self):
        rows = [
            {"id": 1, "name": "Good Stadium", "dome": False, "latitude": 41.88, "longitude": -87.62},
            {"id": 2, "name": "Broken Stadium", "dome": False},
            {"id": 3, "name": "Nested Stadium", "dome": True, "location": {"latitude": 33.44, "longitude": -112.07}},
        ]
        by_id, _by_name = venue_indexes(rows)
        self.assertIn("1", by_id)
        self.assertIn("3", by_id)
        self.assertNotIn("2", by_id)
        self.assertIsNone(try_venue_coordinates(rows[1]))


if __name__ == "__main__":
    unittest.main()
