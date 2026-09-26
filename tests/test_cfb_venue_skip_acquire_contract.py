from __future__ import annotations

import unittest

from sportsedge.sports.cfb.venue_coordinates import try_venue_coordinates, venue_indexes
from scripts.acquire_cfb_reconstructed_selection import _resolve_venue


class TestAcquireVenueSkipContract(unittest.TestCase):
    def test_index_keeps_good_venues_and_drops_incomplete(self):
        rows = [
            {"id": 10, "name": "Camp Randall", "dome": False, "latitude": 43.07, "longitude": -89.41},
            {"id": 11, "name": "Missing Coords", "dome": False},
            {"id": 12, "name": "State Farm Stadium", "dome": True, "location": {"y": 33.5275, "x": -112.262}}
        ]
        by_id, by_name = venue_indexes(rows)
        self.assertEqual(set(by_id), {"10", "12"})
        self.assertIn("camp randall", by_name)
        self.assertIsNone(try_venue_coordinates(rows[1]))

    def test_unresolved_game_is_skipped_not_raised(self):
        rows = [
            {"id": 10, "name": "Camp Randall", "dome": False, "latitude": 43.07, "longitude": -89.41},
        ]
        by_id, by_name = venue_indexes(rows)
        resolved = _resolve_venue(
            {"id": 999, "venue": "Unknown Bowl", "venueId": 404},
            by_id=by_id,
            by_name=by_name,
        )
        self.assertIsNone(resolved)
        known = _resolve_venue(
            {"id": 1, "venueId": 10, "venue": "Camp Randall"},
            by_id=by_id,
            by_name=by_name,
        )
        self.assertEqual(known["venue_id"], "10")


if __name__ == "__main__":
    unittest.main()
