import json
import unittest
from urllib.request import urlopen


class LiveVenueIdProbe(unittest.TestCase):
    def test_print_2026_mlb_team_venues(self):
        url = "https://statsapi.mlb.com/api/v1/teams?sportId=1&season=2026"
        with urlopen(url, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        rows = []
        for team in payload.get("teams", []):
            venue = team.get("venue") or {}
            rows.append((int(team["id"]), team["name"], venue.get("id"), venue.get("name")))
        rows.sort()
        self.assertEqual(len(rows), 30)
        for row in rows:
            print("VENUE_ROW", json.dumps(row, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
