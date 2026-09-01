import unittest

from scripts.run_nfl_production_validation import bridge_preopening_away_origins
from sportsedge.sports.nfl.m2_history_policy import bridge_postclosing_away_origins


class NFLStadiumHomeOriginBridgeTests(unittest.TestCase):
    def _future_stadium(self, *, first="2016-09-18"):
        return {
            "team_fastr": "MIN",
            "team": "MIN",
            "stadium": "MIN01",
            "first_game_date": first,
            "last_game_date": "2027-01-10",
            "lat": "44.9736273",
            "lon": "-93.2574111",
            "tz_offset": "-6",
        }

    def test_bounded_preopening_away_origin_is_bridged_to_future_stadium(self):
        schedule = [{
            "game_id": "2016_01_MIN_TEN",
            "season": 2016,
            "game_type": "REG",
            "gameday": "2016-09-11",
            "away_team": "MIN",
            "home_team": "TEN",
        }]
        resolved, bridges = bridge_preopening_away_origins(schedule, [self._future_stadium()])
        self.assertEqual(len(bridges), 1)
        self.assertEqual(bridges[0]["team"], "MIN")
        self.assertEqual(bridges[0]["gap_days"], 7)
        self.assertEqual(bridges[0]["reason"], "PRE_OPENING_AWAY_TEAM_HOME_ORIGIN_PROXY")
        synthetic = next(row for row in resolved if row["first_game_date"] == "2016-09-11")
        self.assertEqual(synthetic["last_game_date"], "2016-09-17")
        self.assertEqual(synthetic["stadium"], "MIN01")

    def test_home_game_is_never_bridged(self):
        schedule = [{
            "game_id": "2016_01_TEN_MIN",
            "season": 2016,
            "game_type": "REG",
            "gameday": "2016-09-11",
            "away_team": "TEN",
            "home_team": "MIN",
        }]
        resolved, bridges = bridge_preopening_away_origins(schedule, [self._future_stadium()])
        self.assertEqual(bridges, [])
        self.assertEqual(resolved, [self._future_stadium()])

    def test_gap_beyond_bound_remains_unresolved(self):
        schedule = [{
            "game_id": "2016_01_MIN_TEN",
            "season": 2016,
            "game_type": "REG",
            "gameday": "2016-08-20",
            "away_team": "MIN",
            "home_team": "TEN",
        }]
        resolved, bridges = bridge_preopening_away_origins(schedule, [self._future_stadium()], max_gap_days=28)
        self.assertEqual(bridges, [])
        self.assertEqual(resolved, [self._future_stadium()])

    def test_same_date_future_candidates_fail_closed(self):
        schedule = [{
            "game_id": "2016_01_MIN_TEN",
            "season": 2016,
            "game_type": "REG",
            "gameday": "2016-09-11",
            "away_team": "MIN",
            "home_team": "TEN",
        }]
        second = self._future_stadium()
        second["stadium"] = "MIN_ALT"
        with self.assertRaisesRegex(ValueError, "NFL_STADIUM_BRIDGE_AMBIGUOUS"):
            bridge_preopening_away_origins(schedule, [self._future_stadium(), second])

    def test_existing_active_origin_wins_without_bridge(self):
        active = self._future_stadium(first="2016-01-01")
        schedule = [{
            "game_id": "2016_01_MIN_TEN",
            "season": 2016,
            "game_type": "REG",
            "gameday": "2016-09-11",
            "away_team": "MIN",
            "home_team": "TEN",
        }]
        resolved, bridges = bridge_preopening_away_origins(schedule, [active])
        self.assertEqual(bridges, [])
        self.assertEqual(resolved, [active])


class NFLPostClosingHomeOriginBridgeTests(unittest.TestCase):
    def _oakland(self, *, last="2019-12-15"):
        return {
            "team_fastr": "OAK",
            "team": "OAK",
            "stadium": "OAK00",
            "first_game_date": "1999-09-26",
            "last_game_date": last,
            "lat": "37.7516083",
            "lon": "-122.2006038",
            "tz_offset": "-8",
        }

    def test_2019_oakland_away_tail_keeps_oakland_as_home_origin(self):
        schedule = [
            {"game_id": "2019_16_OAK_LAC", "game_type": "REG", "gameday": "2019-12-22", "away_team": "OAK", "home_team": "LAC"},
            {"game_id": "2019_17_OAK_DEN", "game_type": "REG", "gameday": "2019-12-29", "away_team": "OAK", "home_team": "DEN"},
        ]
        resolved = bridge_postclosing_away_origins(schedule, [self._oakland()])
        self.assertEqual(resolved[0]["stadium"], "OAK00")
        self.assertEqual(resolved[0]["last_game_date"], "2019-12-29")
        self.assertEqual(resolved[0]["sportsedge_source_last_game_date"], "2019-12-15")
        self.assertEqual(resolved[0]["sportsedge_origin_bridge"], "POST_CLOSING_AWAY_TEAM_HOME_ORIGIN_PROXY")

    def test_postclosing_bridge_never_uses_future_relocation_stadium(self):
        vegas = {
            "team_fastr": "LV",
            "team": "OAK",
            "stadium": "VEG00",
            "first_game_date": "2020-09-21",
            "last_game_date": "2026-12-27",
            "lat": "36.0908515",
            "lon": "-115.1833441",
            "tz_offset": "-8",
        }
        schedule = [{"game_id": "2019_16_OAK_LAC", "game_type": "REG", "gameday": "2019-12-22", "away_team": "OAK", "home_team": "LAC"}]
        resolved = bridge_postclosing_away_origins(schedule, [self._oakland(), vegas])
        oak = next(row for row in resolved if row["stadium"] == "OAK00")
        lv = next(row for row in resolved if row["stadium"] == "VEG00")
        self.assertEqual(oak["last_game_date"], "2019-12-22")
        self.assertEqual(lv["first_game_date"], "2020-09-21")

    def test_postclosing_home_game_is_not_bridged(self):
        schedule = [{"game_id": "2019_16_DEN_OAK", "game_type": "REG", "gameday": "2019-12-22", "away_team": "DEN", "home_team": "OAK"}]
        self.assertEqual(bridge_postclosing_away_origins(schedule, [self._oakland()]), [self._oakland()])

    def test_postclosing_gap_cannot_chain_beyond_original_28_day_boundary(self):
        schedule = [
            {"game_id": "g1", "game_type": "REG", "gameday": "2019-12-22", "away_team": "OAK", "home_team": "LAC"},
            {"game_id": "g2", "game_type": "REG", "gameday": "2020-01-20", "away_team": "OAK", "home_team": "DEN"},
        ]
        resolved = bridge_postclosing_away_origins(schedule, [self._oakland()], max_gap_days=28)
        self.assertEqual(resolved[0]["last_game_date"], "2019-12-22")


if __name__ == "__main__":
    unittest.main()
