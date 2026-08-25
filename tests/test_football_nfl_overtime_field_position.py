import unittest


class NFLOvertimeFieldPositionTests(unittest.TestCase):
    def _regulation(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        raw = FootballPlayPath(
            "NFL_OT_FP",
            1,
            "HOME",
            "AWAY",
            (
                PlayEvent(
                    1, 1, 1, 700, "HOME", 0, 0, 6, 0,
                    1, 5, 5, "RUSH", 5, 6,
                    score_type="TOUCHDOWN_CANDIDATE",
                ),
                PlayEvent(
                    2, 2, 4, 100, "AWAY", 6, 0, 6, 6,
                    1, 5, 5, "RUSH", 5, 6,
                    score_type="TOUCHDOWN_CANDIDATE",
                ),
            ),
        )
        return EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME", kicker_id="H_K", kicker_active=True,
                fg_base_skill=1.0, xp_make_rate=1.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY", kicker_id="A_K", kicker_active=True,
                fg_base_skill=1.0, xp_make_rate=1.0,
            ),
            seed=1,
        ).resolve(raw)

    def _offense(self, **overrides):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile

        data = dict(
            pass_rate=0.0,
            completion_rate=1.0,
            success_rate=0.0,
            explosive_rate=0.0,
            turnover_rate=0.0,
            sack_rate=0.0,
            field_goal_attempt_rate=0.0,
            pace_seconds_mean=20.0,
        )
        data.update(overrides)
        return TeamDriveProfile(**data)

    def _field(self, team, **overrides):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile

        data = dict(
            team=team,
            deep_touchback_rate=1.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=40.0,
            punt_net_yards_sd=0.0,
            onside_attempt_rate_when_trailing=0.0,
            onside_recovery_rate=0.0,
        )
        data.update(overrides)
        return NFLFieldPositionProfile(**data)

    def test_opening_ot_touchback_drives_from_own_35_not_fixed_25(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=self._field("HOME"),
            away_field_position=self._field("AWAY"),
            seed=20260825,
        ).simulate()
        self.assertTrue(result.transitions)
        opening = result.transitions[0]
        self.assertEqual(opening.period, 5)
        self.assertTrue(opening.transition_type.startswith("OT_OPENING_KICKOFF_TOUCHBACK_35"))
        first_scrimmage = next(
            play for play in result.plays
            if play.opportunity_index == 1 and play.play_type in {"PASS", "RUSH", "SACK", "FIELD_GOAL", "PUNT"}
        )
        self.assertEqual(first_scrimmage.yardline_100, 65)

    def test_opening_ot_onside_recovery_credits_receiver_opportunity_then_starts_kicker(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        home_field = self._field(
            "HOME",
            deep_touchback_rate=0.0,
            onside_attempt_rate_when_trailing=1.0,
            onside_recovery_rate=1.0,
        )
        away_field = self._field(
            "AWAY",
            deep_touchback_rate=0.0,
            onside_attempt_rate_when_trailing=1.0,
            onside_recovery_rate=1.0,
        )
        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=home_field,
            away_field_position=away_field,
            seed=9,
        ).simulate()
        self.assertEqual(result.opportunities[0].outcome_type, "ONSIDE_RECOVERED_KICKING")
        self.assertEqual(result.opportunities[0].points, 0)
        opening = result.transitions[0]
        self.assertEqual(opening.transition_type, "ONSIDE_RECOVERED_KICKING")
        self.assertFalse(opening.kicking_team_was_trailing)
        second_scrimmage = next(
            play for play in result.plays
            if play.opportunity_index == 2 and play.play_type in {"PASS", "RUSH", "SACK", "FIELD_GOAL", "PUNT"}
        )
        self.assertEqual(second_scrimmage.opportunity_team, opening.next_possession_team)
        self.assertEqual(second_scrimmage.yardline_100, opening.next_yardline_100)

    def test_opening_kickoff_return_td_is_first_opportunity_score_and_gets_required_try(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator
        from sportsedge.core.simulate.return_scoring import NFLReturnScoringProfile

        home_field = self._field("HOME", deep_touchback_rate=0.0)
        away_field = self._field("AWAY", deep_touchback_rate=0.0)
        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=home_field,
            away_field_position=away_field,
            home_return_scoring=NFLReturnScoringProfile("HOME", kickoff_return_td_rate=1.0),
            away_return_scoring=NFLReturnScoringProfile("AWAY", kickoff_return_td_rate=1.0),
            seed=11,
        ).simulate()
        first = result.opportunities[0]
        self.assertEqual(first.outcome_type, "KICKOFF_RETURN_TOUCHDOWN_WITH_TRY")
        self.assertEqual(first.points, 7)
        return_play = next(
            play for play in result.plays
            if play.opportunity_index == 1 and play.play_type == "KICKOFF_RETURN"
        )
        self.assertEqual(return_play.return_points, 6)
        self.assertEqual(return_play.special_teams_points, 1)
        self.assertEqual(return_play.return_scoring_team, first.scoring_team)
        self.assertFalse(result.transitions[0].creates_next_drive)

    def test_punt_transition_starts_next_opportunity_at_resolved_spot(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        simulator = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=self._field("HOME"),
            away_field_position=self._field("AWAY"),
            seed=14,
        )
        transition = simulator._resolve_punt_transition(
            transition_index=0,
            source_play_index=1,
            punting_team="HOME",
            receiving_team="AWAY",
            clock_remaining=500,
            kicking_yardline_100=70,
        )
        self.assertEqual(transition.period, 5)
        self.assertEqual(transition.transition_type, "PUNT_RETURN")
        self.assertEqual(transition.next_possession_team, "AWAY")
        self.assertEqual(transition.next_yardline_100, 70)

    def test_ot_transition_sequence_is_contiguous_and_only_drive_transitions_start_scrimmage(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        result = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._offense(),
            away_profile=self._offense(),
            home_field_position=self._field("HOME"),
            away_field_position=self._field("AWAY"),
            seed=5,
        ).simulate()
        indexes = [transition.transition_index for transition in result.transitions]
        self.assertEqual(indexes, list(range(1, len(indexes) + 1)))
        result.assert_reconciliation()


if __name__ == "__main__":
    unittest.main()
