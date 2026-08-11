import unittest
from datetime import datetime, timezone

from sportsedge.mlb_source import (
    parse_schedule, parse_confirmed_lineup, parse_game_start,
    game_time_chicago, snapshot_to_dict, MLBSourceError,
)


class MLBSourceTests(unittest.TestCase):
    def _game(self, game_pk=746381, game_date="2024-06-15T20:10:00Z"):
        return {
            "gamePk": game_pk,
            "gameDate": game_date,
            "status":{"detailedState":"Scheduled"},
            "teams":{
                "away":{"team":{"id":116,"name":"Detroit Tigers"},"probablePitcher":{"id":1,"fullName":"Away P"}},
                "home":{"team":{"id":117,"name":"Houston Astros"},"probablePitcher":{"id":2,"fullName":"Home P"}},
            }
        }

    def test_schedule_identity_and_probables(self):
        game = self._game()
        game.update({"gameNumber":2,"doubleHeader":"Y","venue":{"id":2392},"officialDate":"2024-06-15"})
        payload = {"dates":[{"games":[game]}]}
        got = parse_schedule(payload, datetime(2026,8,10,tzinfo=timezone.utc))[0]
        self.assertEqual(got.game_pk, 746381)
        self.assertEqual(got.home_probable_pitcher_id, 2)
        self.assertEqual(got.source, "MLB_STATSAPI_SCHEDULE")
        self.assertEqual(got.game_date, "2024-06-15T20:10:00+00:00")
        self.assertEqual((got.game_number,got.double_header,got.venue_id,got.official_date),(2,"Y",2392,"2024-06-15"))

    def test_doubleheader_without_game_number_blocks(self):
        game=self._game(); game["doubleHeader"]="Y"
        with self.assertRaisesRegex(MLBSourceError,"doubleheader game missing gameNumber"):
            parse_schedule({"dates":[{"games":[game]}]}, datetime(2026,8,10,tzinfo=timezone.utc))

    def test_invalid_doubleheader_flag_blocks(self):
        game=self._game(); game["doubleHeader"]="X"; game["gameNumber"]=1
        with self.assertRaises(MLBSourceError):
            parse_schedule({"dates":[{"games":[game]}]}, datetime(2026,8,10,tzinfo=timezone.utc))

    def test_schedule_missing_identity_blocks(self):
        payload = {"dates":[{"games":[{"gamePk":1,"gameDate":"2026-08-10T20:00:00Z","teams":{"away":{"team":{}},"home":{"team":{"id":2}}}}]}]}
        with self.assertRaises(MLBSourceError):
            parse_schedule(payload, datetime(2026,8,10,tzinfo=timezone.utc))

    def test_missing_or_naive_game_time_blocks(self):
        for value in (None, "", "2026-08-10T18:07:00"):
            with self.subTest(value=value), self.assertRaises(MLBSourceError):
                parse_game_start(value)

    def test_provider_offset_normalizes_to_utc_then_chicago(self):
        dt = parse_game_start("2026-08-10T23:07:00Z")
        self.assertEqual(dt.isoformat(), "2026-08-10T23:07:00+00:00")
        self.assertEqual(game_time_chicago(dt.isoformat()), "2026-08-10T18:07:00-05:00")

    def test_schedule_sorted_by_true_instant_not_input_order(self):
        payload = {"dates":[{"games":[
            self._game(2, "2026-08-11T02:10:00Z"),
            self._game(1, "2026-08-10T23:07:00Z"),
        ]}]}
        got = parse_schedule(payload, datetime(2026,8,10,tzinfo=timezone.utc))
        self.assertEqual([x.game_pk for x in got], [1,2])

    def test_duplicate_gamepk_blocks_even_if_times_differ(self):
        payload = {"dates":[{"games":[
            self._game(1, "2026-08-10T23:07:00Z"),
            self._game(1, "2026-08-11T02:10:00Z"),
        ]}]}
        with self.assertRaises(MLBSourceError):
            parse_schedule(payload, datetime(2026,8,10,tzinfo=timezone.utc))

    def test_snapshot_dict_exposes_utc_and_chicago_times(self):
        snap = parse_schedule({"dates":[{"games":[self._game(1, "2026-08-10T23:07:00Z")]}]}, datetime(2026,8,10,tzinfo=timezone.utc))[0]
        out = snapshot_to_dict(snap)
        self.assertEqual(out["game_time_utc"], "2026-08-10T23:07:00+00:00")
        self.assertEqual(out["game_time_ct"], "2026-08-10T18:07:00-05:00")

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
