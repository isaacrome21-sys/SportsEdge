import unittest


class NFL2026FieldPositionRuleTests(unittest.TestCase):
    def _profiles(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile

        home = NFLFieldPositionProfile(
            team="HOME",
            deep_touchback_rate=0.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=40.0,
            punt_net_yards_sd=0.0,
            onside_attempt_rate_when_trailing=1.0,
            onside_recovery_rate=1.0,
        )
        away = NFLFieldPositionProfile(
            team="AWAY",
            deep_touchback_rate=1.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=40.0,
            punt_net_yards_sd=0.0,
            onside_attempt_rate_when_trailing=0.0,
            onside_recovery_rate=0.0,
        )
        return home, away

    def test_2026_declared_onside_can_be_attempted_when_not_trailing(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        event = NFLFieldPositionResolver(home, away, seed=1).kickoff(
            transition_index=1,
            source_play_id=10,
            next_drive_id=2,
            kicking_team="HOME",
            receiving_team="AWAY",
            period=1,
            clock_seconds_remaining=600,
            kicking_team_trailing=False,
            allow_onside=True,
        )
        self.assertEqual(event.transition_type, "ONSIDE_RECOVERED_KICKING")
        self.assertEqual(event.next_possession_team, "HOME")
        self.assertFalse(event.kicking_team_was_trailing)

    def test_allow_onside_false_still_forces_ordinary_kick(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        event = NFLFieldPositionResolver(home, away, seed=1).kickoff(
            transition_index=1,
            source_play_id=None,
            next_drive_id=1,
            kicking_team="HOME",
            receiving_team="AWAY",
            period=5,
            clock_seconds_remaining=600,
            kicking_team_trailing=False,
            label="OT_OPENING_KICKOFF",
            allow_onside=False,
        )
        self.assertNotIn("ONSIDE", event.transition_type)
        self.assertEqual(event.period, 5)
        self.assertEqual(event.clock_seconds_remaining, 600)

    def test_ot_transition_clock_accepts_period_five_only_up_to_600_seconds(self):
        from sportsedge.core.simulate.field_position import NFLPossessionTransition

        event = NFLPossessionTransition(
            transition_index=1,
            transition_type="OT_OPENING_KICKOFF_TOUCHBACK_35",
            source_play_id=None,
            next_drive_id=1,
            period=5,
            clock_seconds_remaining=600,
            from_team="AWAY",
            nominal_receiving_team="HOME",
            next_possession_team="HOME",
            next_yardline_100=65,
        )
        self.assertEqual(event.period, 5)
        with self.assertRaisesRegex(ValueError, "FIELD_POSITION_CLOCK_INVALID"):
            NFLPossessionTransition(
                transition_index=2,
                transition_type="OT_KICKOFF_TOUCHBACK_35",
                source_play_id=None,
                next_drive_id=2,
                period=5,
                clock_seconds_remaining=601,
                from_team="HOME",
                nominal_receiving_team="AWAY",
                next_possession_team="AWAY",
                next_yardline_100=65,
            )

    def test_regulation_clock_still_allows_900_but_period_six_is_rejected(self):
        from sportsedge.core.simulate.field_position import NFLPossessionTransition

        NFLPossessionTransition(
            transition_index=1,
            transition_type="OPENING_KICKOFF_TOUCHBACK_35",
            source_play_id=None,
            next_drive_id=1,
            period=1,
            clock_seconds_remaining=900,
            from_team="AWAY",
            nominal_receiving_team="HOME",
            next_possession_team="HOME",
            next_yardline_100=65,
        )
        with self.assertRaisesRegex(ValueError, "FIELD_POSITION_PERIOD_INVALID"):
            NFLPossessionTransition(
                transition_index=2,
                transition_type="BAD",
                source_play_id=None,
                next_drive_id=2,
                period=6,
                clock_seconds_remaining=1,
                from_team="HOME",
                nominal_receiving_team="AWAY",
                next_possession_team="AWAY",
                next_yardline_100=65,
            )


if __name__ == "__main__":
    unittest.main()
