import unittest


class NFLReturnScoringTests(unittest.TestCase):
    def _simulator(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile
        from sportsedge.core.simulate.field_position import NFLFieldPositionProfile
        from sportsedge.core.simulate.regulation_simulator import NFLIntegratedRegulationSimulator
        from sportsedge.core.simulate.return_scoring import NFLReturnScoringProfile
        from sportsedge.core.simulate.special_teams import SpecialTeamsProfile

        offense = TeamDriveProfile(
            pass_rate=0.5,
            completion_rate=0.65,
            success_rate=0.45,
            explosive_rate=0.1,
            turnover_rate=0.0,
            sack_rate=0.0,
            field_goal_attempt_rate=0.0,
            pace_seconds_mean=30.0,
        )
        home_field = NFLFieldPositionProfile(
            team="HOME",
            deep_touchback_rate=0.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=0.0,
            punt_net_yards_sd=0.0,
        )
        away_field = NFLFieldPositionProfile(
            team="AWAY",
            deep_touchback_rate=0.0,
            landing_touchback_rate=0.0,
            kickoff_return_yards_mean=25.0,
            kickoff_return_yards_sd=0.0,
            punt_net_yards_mean=0.0,
            punt_net_yards_sd=0.0,
        )
        return NFLIntegratedRegulationSimulator(
            game_id="NFL_RETURN_TEST",
            home_team="HOME",
            away_team="AWAY",
            home_profile=offense,
            away_profile=offense,
            home_special_teams=SpecialTeamsProfile(
                team="HOME", kicker_id="H_K", kicker_active=True,
                fg_base_skill=1.0, xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
            ),
            away_special_teams=SpecialTeamsProfile(
                team="AWAY", kicker_id="A_K", kicker_active=True,
                fg_base_skill=1.0, xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
            ),
            home_field_position=home_field,
            away_field_position=away_field,
            home_return_scoring=NFLReturnScoringProfile(
                "HOME",
                kickoff_return_td_rate=1.0,
                punt_return_td_rate=1.0,
                turnover_return_td_rate=1.0,
            ),
            away_return_scoring=NFLReturnScoringProfile(
                "AWAY",
                kickoff_return_td_rate=0.0,
                punt_return_td_rate=0.0,
                turnover_return_td_rate=0.0,
            ),
            seed=20260825,
        )

    def test_defensive_return_td_play_allows_incomplete_interception_score_only(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        play = PlayEvent(
            1, 1, 2, 500, "AWAY",
            0, 0, 6, 0,
            1, 10, 65,
            "PASS", 0, 6,
            score_type="DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE",
            turnover_type="INTERCEPTION",
            pass_complete=False,
        )
        self.assertEqual(play.points, 6)
        with self.assertRaisesRegex(ValueError, "INCOMPLETE_PASS_STATE_INVALID"):
            PlayEvent(
                1, 2, 2, 480, "AWAY",
                6, 0, 12, 0,
                1, 10, 65,
                "PASS", 0, 6,
                score_type="TOUCHDOWN_CANDIDATE",
                pass_complete=False,
            )

    def test_special_teams_resolver_uses_defensive_scoring_team_for_return_td_try(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        raw = FootballPlayPath(
            "NFL_RETURN_RAW",
            1,
            "HOME",
            "AWAY",
            (
                PlayEvent(
                    1, 1, 1, 400, "AWAY",
                    0, 0, 6, 0,
                    1, 10, 70,
                    "PASS", 0, 6,
                    score_type="DEFENSIVE_RETURN_TOUCHDOWN_CANDIDATE",
                    turnover_type="INTERCEPTION",
                    pass_complete=False,
                ),
            ),
        )
        resolved = EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME", kicker_id="H_K", kicker_active=True,
                xp_make_rate=1.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY", kicker_id="A_K", kicker_active=True,
                xp_make_rate=0.0,
            ),
            seed=3,
        ).resolve(raw)
        resolved.assert_reconciliation()
        self.assertEqual(len(resolved.special_teams_events), 1)
        event = resolved.special_teams_events[0]
        self.assertEqual(event.team, "HOME")
        self.assertEqual(event.event_type, "XP_MADE")
        self.assertEqual(resolved.to_scoring_path().to_market_row()["home_score"], 7)

    def test_kickoff_return_td_is_non_drive_then_try_then_ensuing_kickoff(self):
        simulator = self._simulator()
        transitions = []
        events = []
        pending, index, home_score, away_score = simulator._kickoff_chain(
            transition_index=0,
            source_play_id=None,
            next_drive_id=1,
            kicking_team="AWAY",
            receiving_team="HOME",
            period=1,
            clock_seconds_remaining=900,
            kicking_team_trailing=False,
            label="OPENING_KICKOFF",
            allow_onside=False,
            transitions=transitions,
            c_events=events,
            resolved_home=0,
            resolved_away=0,
        )
        self.assertEqual(index, 2)
        self.assertEqual((home_score, away_score), (7, 0))
        self.assertEqual(len(transitions), 2)
        self.assertFalse(transitions[0].creates_next_drive)
        self.assertTrue(transitions[0].transition_type.endswith("_RETURN_TD"))
        self.assertTrue(transitions[1].creates_next_drive)
        self.assertEqual(pending, transitions[1])
        self.assertEqual(pending.next_possession_team, "AWAY")
        self.assertEqual([event.event_type for event in events], ["KICKOFF_RETURN_TD", "XP_MADE"])
        self.assertEqual(events[0].source_transition_index, transitions[0].transition_index)
        self.assertEqual(events[1].source_transition_index, transitions[0].transition_index)

    def test_punt_return_td_flows_into_try_and_ensuing_kickoff(self):
        from sportsedge.core.simulate.drive_play import PlayEvent

        simulator = self._simulator()
        punt = PlayEvent(
            1, 1, 2, 500, "AWAY",
            0, 0, 0, 0,
            4, 10, 70,
            "PUNT", 0, 0,
        )
        transitions = []
        events = []
        pending, index, home_score, away_score = simulator._punt_transition(
            transition_index=0,
            play=punt,
            next_drive_id=2,
            punting_team="AWAY",
            receiving_team="HOME",
            period=2,
            clock_seconds_remaining=500,
            kicking_yardline_100=70,
            transitions=transitions,
            c_events=events,
            resolved_home=0,
            resolved_away=0,
        )
        self.assertEqual(index, 2)
        self.assertEqual((home_score, away_score), (7, 0))
        self.assertEqual(transitions[0].transition_type, "PUNT_RETURN_TD")
        self.assertFalse(transitions[0].creates_next_drive)
        self.assertEqual([event.event_type for event in events], ["PUNT_RETURN_TD", "XP_MADE"])
        self.assertTrue(pending.creates_next_drive)
        self.assertEqual(pending.next_possession_team, "AWAY")

    def test_return_scoring_resolver_is_seeded_market_blind_and_bounded(self):
        from sportsedge.core.simulate.return_scoring import NFLReturnScoringProfile, NFLReturnScoringResolver

        home = NFLReturnScoringProfile("HOME", kickoff_return_td_rate=1.0)
        away = NFLReturnScoringProfile("AWAY", kickoff_return_td_rate=0.0)
        resolver = NFLReturnScoringResolver(home, away, seed=9)
        self.assertTrue(resolver.is_touchdown("HOME", "KICKOFF"))
        self.assertFalse(resolver.is_touchdown("AWAY", "KICKOFF"))
        with self.assertRaisesRegex(ValueError, "RETURN_SCORING_RATE_OUT_OF_RANGE"):
            NFLReturnScoringProfile("HOME", turnover_return_td_rate=1.1)
        with self.assertRaises(TypeError):
            NFLReturnScoringResolver(home, away, seed=9, spread_line=-3.0)


if __name__ == "__main__":
    unittest.main()
