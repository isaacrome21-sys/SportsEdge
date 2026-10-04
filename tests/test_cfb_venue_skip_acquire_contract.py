from __future__ import annotations

import unittest

from scripts.acquire_cfb_reconstructed_selection import _resolve_venue
from sportsedge.sports.cfb.venue_coordinates import try_venue_coordinates, venue_indexes


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

    def test_unresolved_game_is_omitted_without_placeholder(self):
        by_id, by_name = venue_indexes([
            {"id": 10, "name": "Camp Randall", "dome": False, "latitude": 43.07, "longitude": -89.41},
        ])
        resolved = _resolve_venue(
            {"game_id": "99", "venue_id": "404", "venue": "Unknown Bowl"},
            by_id=by_id,
            by_name=by_name,
        )
        self.assertIsNone(resolved)
        blob = str(by_id)
        self.assertNotIn("PLACEHOLDER", blob)


if __name__ == "__main__":
    unittest.main()
