import unittest


class FootballSituationalReadoutTests(unittest.TestCase):
    def _path(self):
        from sportsedge.core.simulate.football_path import FootballGamePath, ScoringEvent

        return FootballGamePath(
            game_id="NFL_TEST",
            simulation_id=1,
            home_team="HOME",
            away_team="AWAY",
            events=(
                ScoringEvent("1", 1, 800, "HOME", 7, "TD_PLUS_TRY_CANDIDATE"),
                ScoringEvent("2", 1, 600, "AWAY", 3, "FIELD_GOAL_CANDIDATE"),
                ScoringEvent("3", 2, 500, "AWAY", 7, "TD_PLUS_TRY_CANDIDATE"),
                ScoringEvent("4", 3, 700, "HOME", 7, "TD_PLUS_TRY_CANDIDATE"),
                ScoringEvent("5", 4, 200, "HOME", 3, "FIELD_GOAL_CANDIDATE"),
                ScoringEvent("6", 5, 300, "AWAY", 7, "TD_PLUS_TRY_CANDIDATE"),
            ),
        )

    def test_race_to_n_uses_event_order_not_final_score(self):
        from sportsedge.core.simulate.situational import derive_race_to_n

        path = self._path()
        race_10 = derive_race_to_n([path], n=10, include_ot=False)
        race_17 = derive_race_to_n([path], n=17, include_ot=False)
        self.assertEqual(race_10["away_first"], 1.0)
        self.assertEqual(race_10["home_first"], 0.0)
        self.assertEqual(race_17["home_first"], 1.0)
        self.assertEqual(race_17["neither"], 0.0)

    def test_race_to_n_exposes_neither_without_guessing_book_settlement(self):
        from sportsedge.core.simulate.situational import derive_race_to_n

        result = derive_race_to_n([self._path()], n=30, include_ot=True)
        self.assertEqual(result, {"home_first": 0.0, "away_first": 0.0, "neither": 1.0})

    def test_largest_lead_is_maximum_intermediate_score_difference(self):
        from sportsedge.core.simulate.situational import derive_largest_lead

        home = derive_largest_lead([self._path()], side="home", line=6.5, include_ot=False)
        away = derive_largest_lead([self._path()], side="away", line=2.5, include_ot=False)
        self.assertEqual(home, {"over": 1.0, "under": 0.0, "push": 0.0})
        self.assertEqual(away, {"over": 1.0, "under": 0.0, "push": 0.0})

    def test_margin_band_uses_explicit_regulation_or_ot_window(self):
        from sportsedge.core.simulate.situational import derive_winning_margin_band

        regulation = derive_winning_margin_band(
            [self._path()], lower=7, upper=7, include_ot=False
        )
        with_ot = derive_winning_margin_band(
            [self._path()], lower=7, upper=7, include_ot=True
        )
        self.assertEqual(regulation, {"in_band": 1.0, "out_of_band": 0.0})
        self.assertEqual(with_ot, {"in_band": 0.0, "out_of_band": 1.0})

    def test_both_teams_to_n_obeys_explicit_ot_window(self):
        from sportsedge.core.simulate.situational import derive_both_teams_to_n

        regulation = derive_both_teams_to_n([self._path()], n=17, include_ot=False)
        with_ot = derive_both_teams_to_n([self._path()], n=17, include_ot=True)
        self.assertEqual(regulation, {"yes": 0.0, "no": 1.0})
        self.assertEqual(with_ot, {"yes": 1.0, "no": 0.0})

    def test_ot_semantics_are_never_implicit(self):
        from sportsedge.core.simulate.situational import derive_race_to_n

        with self.assertRaisesRegex(TypeError, "include_ot"):
            derive_race_to_n([self._path()], n=10)

    def test_invalid_thresholds_and_sides_fail_closed(self):
        from sportsedge.core.simulate.situational import derive_both_teams_to_n, derive_largest_lead

        with self.assertRaisesRegex(ValueError, "POINT_THRESHOLD_MUST_BE_POSITIVE"):
            derive_both_teams_to_n([self._path()], n=0, include_ot=False)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_TEAM_SIDE"):
            derive_largest_lead([self._path()], side="draw", line=1.5, include_ot=False)


if __name__ == "__main__":
    unittest.main()
