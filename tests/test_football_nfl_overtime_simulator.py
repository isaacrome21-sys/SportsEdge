import unittest


class NFLPredictiveOvertimeSimulatorTests(unittest.TestCase):
    def _regulation(self, *, tied=True):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        plays = [
            PlayEvent(
                1, 1, 1, 700, "HOME", 0, 0, 6, 0, 1, 5, 5,
                "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE",
            ),
        ]
        if tied:
            plays.append(
                PlayEvent(
                    2, 2, 4, 100, "AWAY", 6, 0, 6, 6, 1, 5, 5,
                    "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE",
                )
            )
        raw = FootballPlayPath("NFL_OT_SIM", 1, "HOME", "AWAY", tuple(plays))
        return EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME", kicker_id="H_K", kicker_active=True,
                fg_base_skill=1.0, xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY", kicker_id="A_K", kicker_active=True,
                fg_base_skill=1.0, xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
            ),
            seed=11,
        ).resolve(raw)

    def _offense(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile

        return TeamDriveProfile(
            pass_rate=0.0,
            completion_rate=1.0,
            success_rate=1.0,
            explosive_rate=1.0,
            turnover_rate=0.0,
            field_goal_attempt_rate=1.0,
            pace_seconds_mean=20.0,
        )

    def _turnover_offense(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile

        return TeamDriveProfile(
            pass_rate=1.0,
            completion_rate=1.0,
            success_rate=0.5,
            explosive_rate=0.0,
            turnover_rate=1.0,
            sack_rate=0.0,
            field_goal_attempt_rate=0.0,
            pace_seconds_mean=20.0,
        )

    def test_seeded_predictive_overtime_is_reproducible_and_terminal(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        regulation = self._regulation()
        profile = self._offense()
        kwargs = dict(
            regulation_path=regulation,
            home_profile=profile,
            away_profile=profile,
            seed=20260825,
        )
        first = NFLRegularSeasonOTSimulator(**kwargs).simulate()
        second = NFLRegularSeasonOTSimulator(**kwargs).simulate()
        self.assertEqual(first, second)
        first.assert_reconciliation()
        self.assertTrue(first.opportunities)
        self.assertTrue(first.plays)
        self.assertTrue(first.settlement.tie or first.settlement.winner in {"HOME", "AWAY"})

    def test_ot_play_clock_is_nonincreasing_and_within_ten_minutes(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            seed=3,
        ).simulate()
        clocks = [play.clock_end_seconds_remaining for play in result.plays]
        self.assertTrue(all(0 <= value <= 600 for value in clocks))
        self.assertEqual(clocks, sorted(clocks, reverse=True))

    def test_first_two_opportunities_are_credited_to_opposite_teams(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            seed=7,
        ).simulate()
        if len(result.opportunities) >= 2:
            self.assertNotEqual(
                result.opportunities[0].opportunity_team,
                result.opportunities[1].opportunity_team,
            )

    def test_touchdowns_use_rule_aware_try_scoring_from_engine_c_profile(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            seed=7,
        ).simulate()
        self.assertEqual(result.opportunities[0].outcome_type, "TOUCHDOWN_WITH_TRY")
        self.assertEqual(result.opportunities[0].points, 7)
        first_plays = [play for play in result.plays if play.opportunity_index == 1]
        self.assertEqual(sum(play.raw_points + play.special_teams_points for play in first_plays), 7)

    def test_sudden_death_touchdown_has_no_post_game_try(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            seed=7,
        ).simulate()
        self.assertGreaterEqual(len(result.opportunities), 3)
        self.assertEqual(result.opportunities[0].points, 7)
        self.assertEqual(result.opportunities[1].points, 7)
        self.assertEqual(result.opportunities[2].outcome_type, "TOUCHDOWN_SUDDEN_DEATH")
        self.assertEqual(result.opportunities[2].points, 6)

    def test_field_goal_resolver_returns_exact_two_value_contract(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        simulator = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            seed=31,
        )
        points, event_type = simulator._resolve_fg("HOME", 40)
        self.assertEqual((points, event_type), (3, "FG_MADE"))

    def test_forced_turnover_return_td_is_terminal_six_without_try(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator
        from sportsedge.core.simulate.return_scoring import NFLReturnScoringProfile

        profile = self._turnover_offense()
        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=profile,
            away_profile=profile,
            home_return_scoring=NFLReturnScoringProfile(
                "HOME", turnover_return_td_rate=1.0,
            ),
            away_return_scoring=NFLReturnScoringProfile(
                "AWAY", turnover_return_td_rate=1.0,
            ),
            seed=41,
        ).simulate()
        self.assertEqual(len(result.opportunities), 1)
        opportunity = result.opportunities[0]
        self.assertEqual(opportunity.outcome_type, "DEFENSIVE_RETURN_TOUCHDOWN")
        self.assertEqual(opportunity.points, 6)
        self.assertNotEqual(opportunity.scoring_team, opportunity.opportunity_team)
        self.assertEqual(result.settlement.winner, opportunity.scoring_team)
        scoring_play = result.plays[-1]
        self.assertEqual(scoring_play.defensive_points, 6)
        self.assertEqual(scoring_play.special_teams_points, 0)
        result.assert_reconciliation()

    def test_defensive_return_td_opportunity_rejects_post_game_try_points(self):
        from sportsedge.core.simulate.overtime import NFLRegularSeasonOTOpportunity

        with self.assertRaisesRegex(ValueError, "OVERTIME_DEFENSIVE_RETURN_TD_POINTS_INVALID"):
            NFLRegularSeasonOTOpportunity(
                opportunity_index=1,
                opportunity_team="HOME",
                scoring_team="AWAY",
                points=7,
                clock_end_seconds_remaining=500,
                outcome_type="DEFENSIVE_RETURN_TOUCHDOWN",
            )

    def test_non_tied_regulation_is_rejected(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        with self.assertRaisesRegex(ValueError, "OVERTIME_REQUIRES_TIED_REGULATION"):
            NFLRegularSeasonOTSimulator(
                regulation_path=self._regulation(tied=False),
                home_profile=self._offense(),
                away_profile=self._offense(),
                seed=1,
            ).simulate()

    def test_simulator_requires_seed_and_is_market_blind(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        regulation = self._regulation()
        profile = self._offense()
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            NFLRegularSeasonOTSimulator(
                regulation_path=regulation,
                home_profile=profile,
                away_profile=profile,
            )
        with self.assertRaises(TypeError):
            NFLRegularSeasonOTSimulator(
                regulation_path=regulation,
                home_profile=profile,
                away_profile=profile,
                seed=1,
                spread_line=-3.0,
            )


if __name__ == "__main__":
    unittest.main()
