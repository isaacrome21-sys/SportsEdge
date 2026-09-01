import unittest

from scripts.run_nfl_production_validation import bridge_preopening_away_origins


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


if __name__ == "__main__":
    unittest.main()
