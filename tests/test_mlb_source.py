import unittest
from datetime import datetime, timezone

from sportsedge.mlb_source import parse_schedule, parse_confirmed_lineup, MLBSourceError


class MLBSourceTests(unittest.TestCase):
    def test_schedule_identity_and_probables(self):
        payload = {"dates":[{"games":[{
            "gamePk":746381,
            "gameDate":"2024-06-15T20:10:00Z",
            "status":{"detailedState":"Scheduled"},
            "teams":{
                "away":{"team":{"id":116,"name":"Detroit Tigers"},"probablePitcher":{"id":1,"fullName":"Away P"}},
                "home":{"team":{"id":117,"name":"Houston Astros"},"probablePitcher":{"id":2,"fullName":"Home P"}},
            }
        }]}]}
        got = parse_schedule(payload, datetime(2026,8,10,tzinfo=timezone.utc))[0]
        self.assertEqual(got.game_pk, 746381)
        self.assertEqual(got.home_probable_pitcher_id, 2)
        self.assertEqual(got.source, "MLB_STATSAPI_SCHEDULE")

    def test_schedule_missing_identity_blocks(self):
        payload = {"dates":[{"games":[{"gamePk":1,"teams":{"away":{"team":{}},"home":{"team":{"id":2}}}}]}]}
        with self.assertRaises(MLBSourceError):
            parse_schedule(payload, datetime(2026,8,10,tzinfo=timezone.utc))

    def test_lineup_decodes_slot_and_substitution(self):
        box = {"teams":{"home":{"players":{
            "ID10":{"person":{"id":10,"fullName":"Starter"},"battingOrder":"300"},
            "ID11":{"person":{"id":11,"fullName":"Sub"},"battingOrder":"301"},
            "ID12":{"person":{"id":12,"fullName":"Bench"}},
        }}}}
        lineup = parse_confirmed_lineup(box, "home")
        self.assertEqual([x["player_id"] for x in lineup], [10,11])
        self.assertFalse(lineup[0]["substitution_evidence"])
        self.assertTrue(lineup[1]["substitution_evidence"])

    def test_bad_side_blocks(self):
        with self.assertRaises(MLBSourceError):
            parse_confirmed_lineup({}, "middle")


if __name__ == "__main__":
    unittest.main()
