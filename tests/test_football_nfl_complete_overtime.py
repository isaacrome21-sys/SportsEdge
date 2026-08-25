import unittest


class NFLCompleteOvertimeTests(unittest.TestCase):
    def _regulation(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        raw = FootballPlayPath(
            "NFL_COMPLETE_OT", 1, "HOME", "AWAY",
            (
                PlayEvent(1, 1, 1, 700, "HOME", 0, 0, 6, 0, 1, 5, 5,
                          "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE"),
                PlayEvent(2, 2, 4, 100, "AWAY", 6, 0, 6, 6, 1, 5, 5,
                          "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE"),
            ),
        )
        return EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile("HOME", "H_K", True, xp_make_rate=1.0),
            away_profile=SpecialTeamsProfile("AWAY", "A_K", True, xp_make_rate=1.0),
            seed=5,
        ).resolve(raw)

    def _offense(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile
        return TeamDriveProfile(
            pass_rate=0.0,
            completion_rate=1.0,
            success_rate=1.0,
            explosive_rate=1.0,
            turnover_rate=0.0,
            sack_rate=0.0,
            field_goal_attempt_rate=1.0,
            pace_seconds_mean=20.0,
        )

    def _touchback_field(self, team):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile
        return NFLFieldPositionProfile(
            team=team,
            deep_touchback_rate=1.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=40.0,
            punt_net_yards_sd=0.0,
        )

    def _no_returns(self, team):
        from sportsedge.core.simulate.return_scoring import NFLReturnScoringProfile
        return NFLReturnScoringProfile(
            team=team,
            kickoff_return_td_rate=0.0,
            punt_return_td_rate=0.0,
            turnover_return_td_rate=0.0,
        )

    def test_opening_touchback_feeds_65_yardline_into_first_scrimmage_opportunity(self):
        from sportsedge.core.simulate.overtime_complete import NFLRegularSeasonCompleteOTSimulator

        result = NFLRegularSeasonCompleteOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=self._touchback_field("HOME"),
            away_field_position=self._touchback_field("AWAY"),
            home_return_scoring=self._no_returns("HOME"),
            away_return_scoring=self._no_returns("AWAY"),
            seed=12,
        ).simulate()
        self.assertEqual(result.transitions[0].transition_type, "OPENING_KICKOFF_TOUCHBACK_35")
        first = next(play for play in result.plays if play.opportunity_index == 1)
        self.assertEqual(first.yardline_100, 65)
        result.assert_reconciliation()

    def test_scoring_first_opportunity_creates_score_kickoff_before_second_scrimmage(self):
        from sportsedge.core.simulate.overtime_complete import NFLRegularSeasonCompleteOTSimulator

        result = NFLRegularSeasonCompleteOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=self._touchback_field("HOME"),
            away_field_position=self._touchback_field("AWAY"),
            home_return_scoring=self._no_returns("HOME"),
            away_return_scoring=self._no_returns("AWAY"),
            seed=7,
        ).simulate()
        self.assertTrue(any(t.transition_type.startswith("SCORE_KICKOFF") for t in result.transitions))
        if len(result.opportunities) >= 2:
            second = next(play for play in result.plays if play.opportunity_index == 2)
            self.assertEqual(second.yardline_100, 65)

    def test_forced_opening_kick_return_td_is_real_first_opportunity_score(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile
        from sportsedge.core.simulate.return_scoring import NFLReturnScoringProfile
        from sportsedge.core.simulate.overtime_complete import NFLRegularSeasonCompleteOTSimulator

        def returnable(team):
            return NFLFieldPositionProfile(
                team=team,
                deep_touchback_rate=0.0,
                landing_touchback_rate=0.0,
                kickoff_return_yards_mean=25.0,
                kickoff_return_yards_sd=0.0,
                punt_net_yards_mean=40.0,
                punt_net_yards_sd=0.0,
            )
        def scoring(team):
            return NFLReturnScoringProfile(
                team=team,
                kickoff_return_td_rate=1.0,
                punt_return_td_rate=0.0,
                turnover_return_td_rate=0.0,
            )

        result = NFLRegularSeasonCompleteOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=returnable("HOME"),
            away_field_position=returnable("AWAY"),
            home_return_scoring=scoring("HOME"),
            away_return_scoring=scoring("AWAY"),
            seed=4,
        ).simulate()
        self.assertEqual(result.opportunities[0].outcome_type, "OPENING_KICKOFF_RETURN_TOUCHDOWN")
        self.assertEqual(result.opportunities[0].points, 7)
        self.assertEqual(result.transitions[0].points, 7)
        result.assert_reconciliation()

    def test_complete_simulator_is_market_blind(self):
        from sportsedge.core.simulate.overtime_complete import NFLRegularSeasonCompleteOTSimulator

        with self.assertRaises(TypeError):
            NFLRegularSeasonCompleteOTSimulator(
                regulation_path=self._regulation(),
                home_profile=self._offense(),
                away_profile=self._offense(),
                seed=1,
                spread_line=-3.0,
            )


if __name__ == "__main__":
    unittest.main()
