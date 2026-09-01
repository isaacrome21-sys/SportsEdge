from __future__ import annotations

from datetime import datetime, timezone
import io
import json
import unittest

from sportsedge.sports.cfb.travel_source import fetch_cfbd_fbs_venue_registry, enrich_rest_travel_payload


class _Resp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self._raw


class CFBTravelSourceTests(unittest.TestCase):
    def test_registry_and_travel_are_objective_and_not_guessed(self):
        payload = [
            {"school":"A","location":{"id":1,"name":"A Field","latitude":40,"longitude":-75,"timezone":"America/New_York","elevation":100}},
            {"school":"B","location":{"id":2,"name":"B Field","latitude":39,"longitude":-104,"timezone":"America/Denver","elevation":5200}},
        ]
        by_team, by_venue, digest, uri = fetch_cfbd_fbs_venue_registry(
            season=2026, cfbd_api_key="x", opener=lambda req, timeout=20: _Resp(payload)
        )
        self.assertEqual(len(digest), 64)
        self.assertIn("/teams/fbs?year=2026", uri)
        out = enrich_rest_travel_payload(
            payload={"team":"A"},
            current_game={"home_team":"B","venue_id":2,"neutral_site":False},
            previous_game={"home":"A","venue_id":1,"neutral":False},
            current_kickoff=datetime(2026, 9, 5, 18, tzinfo=timezone.utc),
            by_team=by_team, by_venue=by_venue,
        )
        self.assertGreater(out["travel_distance_km"], 1000)
        self.assertEqual(out["timezone_shift_hours"], -2.0)
        self.assertEqual(out["destination_elevation_ft"], 5200.0)
        self.assertEqual(out["travel_status"], "AVAILABLE")

    def test_unresolved_neutral_venue_stays_missing(self):
        by_team = {"A":{"venue_id":"1","latitude":40.0,"longitude":-75.0,"timezone":"America/New_York","elevation_ft":100.0}}
        out = enrich_rest_travel_payload(
            payload={"team":"A"},
            current_game={"home_team":"B","venue_id":999,"neutral_site":True},
            previous_game={"home":"A","venue_id":1,"neutral":False},
            current_kickoff=datetime(2026, 9, 5, 18, tzinfo=timezone.utc),
            by_team=by_team, by_venue={"1":by_team["A"]},
        )
        self.assertIsNone(out["travel_distance_km"])
        self.assertEqual(out["travel_status"], "UNAVAILABLE_UNRESOLVED_VENUE")


if __name__ == "__main__":
    unittest.main()
