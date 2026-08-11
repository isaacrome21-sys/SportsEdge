import json
import unittest
from urllib.parse import urlencode
from urllib.request import urlopen

BASE = "https://statsapi.mlb.com/api/v1"


def get(player_id):
    params = urlencode({"stats":"gameLog","group":"fielding","season":2026,"gameType":"R"})
    with urlopen(f"{BASE}/people/{player_id}/stats?{params}", timeout=15) as response:
        return json.loads(response.read().decode())


class LiveFieldingStartSchemaProbe(unittest.TestCase):
    def test_fielding_game_log_exposes_true_starts_including_dh(self):
        for player_id, label in ((514888, "ALTUVE"), (660271, "OHTANI")):
            payload = get(player_id)
            rows = ((payload.get("stats") or [{}])[0].get("splits") or [])
            self.assertTrue(rows, f"no fielding rows for {label}")
            usable = []
            for row in rows:
                stat = row.get("stat") or {}
                if "gamesStarted" in stat:
                    usable.append(row)
            self.assertTrue(usable, f"no gamesStarted rows for {label}")
            sample = usable[-5:]
            print(label + "_FIELDING", json.dumps([
                {"date": r.get("date"), "game": r.get("game"), "position": r.get("position"), "stat": r.get("stat")}
                for r in sample
            ], sort_keys=True))
            self.assertTrue(any(int((r.get("stat") or {}).get("gamesStarted", 0)) > 0 for r in usable), f"no starts for {label}")


if __name__ == "__main__": unittest.main()
