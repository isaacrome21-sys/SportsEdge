import unittest


class NFLFieldPositionResolverTests(unittest.TestCase):
    def _profiles(self, **home_overrides):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile

        home = dict(
            team="HOME",
            deep_touchback_rate=1.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=40.0,
            punt_net_yards_sd=0.0,
            onside_attempt_rate_when_trailing=0.0,
            onside_recovery_rate=0.0,
        )
        home.update(home_overrides)
        return NFLFieldPositionProfile(**home), NFLFieldPositionProfile(
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

    def test_2026_deep_touchback_starts_receiving_team_at_own_35(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        event = NFLFieldPositionResolver(home, away, seed=1).kickoff(
            transition_index=1,
            source_play_id=None,
            next_drive_id=1,
            kicking_team="AWAY",
            receiving_team="HOME",
            period=1,
            clock_seconds_remaining=900,
            kicking_team_trailing=False,
            label="OPENING_KICKOFF",
        )
        self.assertEqual(event.transition_type, "OPENING_KICKOFF_TOUCHBACK_35")
        self.assertEqual(event.next_possession_team, "HOME")
        self.assertEqual(event.next_yardline_100, 65)

    def test_landing_zone_touchback_uses_own_20(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile, NFLFieldPositionResolver

        home = NFLFieldPositionProfile(
            team="HOME", deep_touchback_rate=0.0, landing_touchback_rate=1.0,
            kickoff_return_yards_mean=25.0, kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=40.0, punt_net_yards_sd=0.0,
            onside_attempt_rate_when_trailing=0.0, onside_recovery_rate=0.0,
        )
        away = NFLFieldPositionProfile(team="AWAY")
        event = NFLFieldPositionResolver(home, away, seed=2).kickoff(
            transition_index=1, source_play_id=10, next_drive_id=4,
            kicking_team="AWAY", receiving_team="HOME", period=2,
            clock_seconds_remaining=300, kicking_team_trailing=False,
        )
        self.assertEqual(event.transition_type, "KICKOFF_TOUCHBACK_20")
        self.assertEqual(event.next_yardline_100, 80)

    def test_2026_declared_onside_is_available_any_time_kicking_team_is_trailing(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles(
            deep_touchback_rate=0.0,
            onside_attempt_rate_when_trailing=1.0,
            onside_recovery_rate=1.0,
        )
        resolver = NFLFieldPositionResolver(home, away, seed=3)
        event = resolver.kickoff(
            transition_index=1, source_play_id=3, next_drive_id=2,
            kicking_team="HOME", receiving_team="AWAY", period=1,
            clock_seconds_remaining=600, kicking_team_trailing=True,
        )
        self.assertEqual(event.transition_type, "ONSIDE_RECOVERED_KICKING")
        self.assertEqual(event.next_possession_team, "HOME")
        self.assertEqual(event.next_yardline_100, 55)

    def test_onside_is_not_attempted_when_kicking_team_is_not_trailing(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles(
            onside_attempt_rate_when_trailing=1.0,
            onside_recovery_rate=1.0,
        )
        event = NFLFieldPositionResolver(home, away, seed=4).kickoff(
            transition_index=1, source_play_id=3, next_drive_id=2,
            kicking_team="HOME", receiving_team="AWAY", period=1,
            clock_seconds_remaining=600, kicking_team_trailing=False,
        )
        self.assertNotIn("ONSIDE", event.transition_type)
        self.assertEqual(event.next_possession_team, "AWAY")

    def test_punt_net_field_position_flips_to_receiving_team_coordinates(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        event = NFLFieldPositionResolver(home, away, seed=5).punt(
            transition_index=1, source_play_id=9, next_drive_id=3,
            punting_team="HOME", receiving_team="AWAY", period=2,
            clock_seconds_remaining=500, kicking_yardline_100=60,
        )
        self.assertEqual(event.transition_type, "PUNT_RETURN")
        self.assertEqual(event.net_kick_yards, 40)
        self.assertEqual(event.next_yardline_100, 80)

    def test_punt_into_end_zone_is_scrimmage_kick_touchback_at_20(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile, NFLFieldPositionResolver

        home = NFLFieldPositionProfile(
            team="HOME", punt_net_yards_mean=70.0, punt_net_yards_sd=0.0,
        )
        away = NFLFieldPositionProfile(team="AWAY")
        event = NFLFieldPositionResolver(home, away, seed=6).punt(
            transition_index=1, source_play_id=9, next_drive_id=3,
            punting_team="HOME", receiving_team="AWAY", period=2,
            clock_seconds_remaining=500, kicking_yardline_100=60,
        )
        self.assertEqual(event.transition_type, "PUNT_TOUCHBACK_20")
        self.assertEqual(event.next_yardline_100, 80)

    def test_missed_field_goal_uses_rule_spot_contract(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        resolver = NFLFieldPositionResolver(home, away, seed=7)
        long_miss = resolver.missed_field_goal(
            transition_index=1, source_play_id=11, next_drive_id=4,
            kicking_team="HOME", receiving_team="AWAY", period=3,
            clock_seconds_remaining=500, line_of_scrimmage_yardline_100=30,
        )
        self.assertEqual(long_miss.next_yardline_100, 63)
        short_miss = resolver.missed_field_goal(
            transition_index=2, source_play_id=12, next_drive_id=5,
            kicking_team="HOME", receiving_team="AWAY", period=3,
            clock_seconds_remaining=400, line_of_scrimmage_yardline_100=10,
        )
        self.assertEqual(short_miss.next_yardline_100, 80)

    def test_turnover_coordinates_are_reversed_without_hidden_return(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        event = NFLFieldPositionResolver(home, away, seed=8).turnover(
            transition_index=1, source_play_id=8, next_drive_id=3,
            offense_team="HOME", defense_team="AWAY", period=1,
            clock_seconds_remaining=500, offense_yardline_100_after_play=40,
            transition_type="INTERCEPTION",
        )
        self.assertEqual(event.next_possession_team, "AWAY")
        self.assertEqual(event.next_yardline_100, 60)

    def test_seed_and_team_identity_are_required_and_market_args_are_rejected(self):
        from sportsedge.core.simulate.field_position import NFLFieldPositionResolver

        home, away = self._profiles()
        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            NFLFieldPositionResolver(home, away)
        with self.assertRaises(TypeError):
            NFLFieldPositionResolver(home, away, seed=1, total_line=45.5)
        with self.assertRaisesRegex(ValueError, "FIELD_POSITION_HOME_AWAY_COLLISION"):
            NFLFieldPositionResolver(home, home, seed=1)


if __name__ == "__main__":
    unittest.main()
