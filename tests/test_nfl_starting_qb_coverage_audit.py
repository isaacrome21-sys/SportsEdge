import unittest

from scripts.run_nfl_production_validation import audit_starting_qb_coverage


class NFLStartingQBCoverageAuditTests(unittest.TestCase):
    def _game(self, *, game_id, season, week, home, away, gameday):
        return {
            "game_id": game_id,
            "season": season,
            "week": week,
            "game_type": "REG",
            "gameday": gameday,
            "gametime": "13:00",
            "home_team": home,
            "away_team": away,
        }

    def _depth(self, *, season, week, team, player):
        return {
            "season": season,
            "week": week,
            "club_code": team,
            "game_type": "REG",
            "depth_team": 1,
            "depth_position": "QB",
            "gsis_id": player,
        }

    def test_reports_all_missing_starters_not_only_first_failure(self):
        schedule = [
            self._game(game_id="2018_01_A_B", season=2018, week=1, home="B", away="A", gameday="2018-09-09"),
            self._game(game_id="2018_01_C_D", season=2018, week=1, home="D", away="C", gameday="2018-09-09"),
        ]
        depth = [
            self._depth(season=2018, week=1, team="A", player="QB_A"),
            self._depth(season=2018, week=1, team="D", player="QB_D"),
        ]
        issues = audit_starting_qb_coverage(schedule, depth, eligible_seasons={2018})
        self.assertEqual([(row["game_id"], row["team"]) for row in issues], [
            ("2018_01_A_B", "B"),
            ("2018_01_C_D", "C"),
        ])
        self.assertTrue(all(str(row["error"]).startswith("NFL_STARTING_QB_MISSING:") for row in issues))

    def test_burn_in_season_is_not_required(self):
        schedule = [self._game(
            game_id="2017_01_A_B", season=2017, week=1, home="B", away="A", gameday="2017-09-10"
        )]
        self.assertEqual(audit_starting_qb_coverage(schedule, [], eligible_seasons={2018}), [])

    def test_ambiguous_rank_one_snapshot_is_reported(self):
        schedule = [self._game(
            game_id="2018_01_A_B", season=2018, week=1, home="B", away="A", gameday="2018-09-09"
        )]
        depth = [
            self._depth(season=2018, week=1, team="A", player="QB_A1"),
            self._depth(season=2018, week=1, team="A", player="QB_A2"),
            self._depth(season=2018, week=1, team="B", player="QB_B"),
        ]
        issues = audit_starting_qb_coverage(schedule, depth, eligible_seasons={2018})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["team"], "A")
        self.assertTrue(str(issues[0]["error"]).startswith("NFL_STARTING_QB_AMBIGUOUS:"))

    def test_prior_week_rank_one_remains_valid_under_production_contract(self):
        schedule = [self._game(
            game_id="2018_02_A_B", season=2018, week=2, home="B", away="A", gameday="2018-09-16"
        )]
        depth = [
            self._depth(season=2018, week=1, team="A", player="QB_A"),
            self._depth(season=2018, week=1, team="B", player="QB_B"),
        ]
        self.assertEqual(audit_starting_qb_coverage(schedule, depth, eligible_seasons={2018}), [])


if __name__ == "__main__":
    unittest.main()
