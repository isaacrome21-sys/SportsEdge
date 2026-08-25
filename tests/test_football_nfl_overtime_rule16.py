import unittest


class NFLRegularSeasonOvertimeRule16Tests(unittest.TestCase):
    def _resolve_raw(self, raw):
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        return EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME", kicker_id="H_K", kicker_active=True,
                xp_make_rate=1.0, two_point_attempt_rate=0.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY", kicker_id="A_K", kicker_active=True,
                xp_make_rate=1.0, two_point_attempt_rate=0.0,
            ),
            seed=1,
        ).resolve(raw)

    def _tied_regulation(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        raw = FootballPlayPath(
            game_id="NFL_OT_TEST",
            simulation_id=1,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 1, 800, "HOME", 0, 0, 6, 0, 1, 5, 5,
                    "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE",
                ),
                PlayEvent(
                    2, 2, 3, 700, "AWAY", 6, 0, 6, 6, 1, 5, 5,
                    "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE",
                ),
            ),
        )
        return self._resolve_raw(raw)

    def _home_lead_regulation(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        raw = FootballPlayPath(
            game_id="NFL_NOT_TIED",
            simulation_id=2,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 2, 700, "HOME", 0, 0, 6, 0, 1, 4, 4,
                    "RUSH", 4, 6, score_type="TOUCHDOWN_CANDIDATE",
                ),
            ),
        )
        return self._resolve_raw(raw)

    def _opp(self, index, team, points, clock, scoring_team=None, outcome="NO_SCORE"):
        from sportsedge.core.simulate.overtime import NFLRegularSeasonOTOpportunity

        return NFLRegularSeasonOTOpportunity(
            opportunity_index=index,
            opportunity_team=team,
            scoring_team=scoring_team,
            points=points,
            clock_end_seconds_remaining=clock,
            outcome_type=outcome,
        )

    def test_opening_touchdown_does_not_end_regular_season_overtime(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        first = self._opp(1, "HOME", 7, 420, "HOME", "TOUCHDOWN_WITH_TRY")
        with self.assertRaisesRegex(ValueError, "OVERTIME_SECOND_OPPORTUNITY_REQUIRED"):
            settle_nfl_regular_season_overtime(self._tied_regulation(), (first,))

    def test_both_teams_get_opportunity_then_higher_score_wins(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (
                self._opp(1, "HOME", 7, 420, "HOME", "TOUCHDOWN_WITH_TRY"),
                self._opp(2, "AWAY", 3, 250, "AWAY", "FIELD_GOAL"),
            ),
        )
        self.assertEqual(result.winner, "HOME")
        self.assertFalse(result.tie)
        row = result.to_scoring_path().to_market_row()
        self.assertEqual(row["ot_home_score"], 7)
        self.assertEqual(row["ot_away_score"], 3)
        self.assertEqual(row["home_score"], 14)
        self.assertEqual(row["away_score"], 10)

    def test_scoreless_first_opportunity_then_second_team_score_wins(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (
                self._opp(1, "HOME", 0, 430),
                self._opp(2, "AWAY", 3, 310, "AWAY", "FIELD_GOAL"),
            ),
        )
        self.assertEqual(result.winner, "AWAY")

    def test_tied_after_both_opportunities_requires_sudden_death_continuation(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        with self.assertRaisesRegex(ValueError, "OVERTIME_SUDDEN_DEATH_CONTINUATION_REQUIRED"):
            settle_nfl_regular_season_overtime(
                self._tied_regulation(),
                (
                    self._opp(1, "HOME", 3, 460, "HOME", "FIELD_GOAL"),
                    self._opp(2, "AWAY", 3, 300, "AWAY", "FIELD_GOAL"),
                ),
            )

    def test_next_score_after_tied_opening_opportunities_is_sudden_death_winner(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (
                self._opp(1, "HOME", 3, 470, "HOME", "FIELD_GOAL"),
                self._opp(2, "AWAY", 3, 320, "AWAY", "FIELD_GOAL"),
                self._opp(3, "HOME", 0, 160),
                self._opp(4, "AWAY", 3, 80, "AWAY", "FIELD_GOAL"),
            ),
        )
        self.assertEqual(result.winner, "AWAY")
        self.assertEqual(result.final_clock_seconds_remaining, 80)

    def test_ten_minute_period_can_expire_before_second_opportunity(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (self._opp(1, "HOME", 3, 0, "HOME", "FIELD_GOAL"),),
        )
        self.assertEqual(result.winner, "HOME")
        self.assertFalse(result.tie)

    def test_ten_minute_period_expiry_tied_is_game_tie(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (self._opp(1, "HOME", 0, 0),),
        )
        self.assertIsNone(result.winner)
        self.assertTrue(result.tie)

    def test_opening_kickoff_safety_exception_ends_game_immediately(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (self._opp(1, "HOME", 2, 590, "AWAY", "KICKOFF_SAFETY"),),
        )
        self.assertEqual(result.winner, "AWAY")
        self.assertFalse(result.tie)

    def test_opportunity_credit_can_represent_kick_recovery_without_offensive_drive(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        result = settle_nfl_regular_season_overtime(
            self._tied_regulation(),
            (
                self._opp(1, "HOME", 3, 470, "HOME", "FIELD_GOAL"),
                self._opp(2, "AWAY", 0, 465, None, "KICK_OPPORTUNITY_NO_POSSESSION"),
            ),
        )
        self.assertEqual(result.winner, "HOME")

    def test_non_tied_regulation_cannot_enter_overtime(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        with self.assertRaisesRegex(ValueError, "OVERTIME_REQUIRES_TIED_REGULATION"):
            settle_nfl_regular_season_overtime(
                self._home_lead_regulation(),
                (self._opp(1, "AWAY", 0, 400),),
            )

    def test_events_after_terminal_state_fail_closed(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        with self.assertRaisesRegex(ValueError, "OVERTIME_EVENTS_AFTER_GAME_END"):
            settle_nfl_regular_season_overtime(
                self._tied_regulation(),
                (
                    self._opp(1, "HOME", 0, 450),
                    self._opp(2, "AWAY", 3, 300, "AWAY", "FIELD_GOAL"),
                    self._opp(3, "HOME", 3, 200, "HOME", "FIELD_GOAL"),
                ),
            )

    def test_clock_and_opportunity_identity_fail_closed(self):
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        with self.assertRaisesRegex(ValueError, "OVERTIME_CLOCK_ORDER_INVALID"):
            settle_nfl_regular_season_overtime(
                self._tied_regulation(),
                (
                    self._opp(1, "HOME", 0, 400),
                    self._opp(2, "AWAY", 0, 450),
                ),
            )
        with self.assertRaisesRegex(ValueError, "OVERTIME_SECOND_OPPORTUNITY_TEAM_INVALID"):
            settle_nfl_regular_season_overtime(
                self._tied_regulation(),
                (
                    self._opp(1, "HOME", 0, 450),
                    self._opp(2, "HOME", 3, 300, "HOME", "FIELD_GOAL"),
                ),
            )


if __name__ == "__main__":
    unittest.main()
