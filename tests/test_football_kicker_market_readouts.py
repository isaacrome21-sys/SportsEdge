import unittest


class FootballKickerMarketReadoutTests(unittest.TestCase):
    def _raw_path(self, simulation_id=1):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent

        return FootballPlayPath(
            game_id="NFL_TEST",
            simulation_id=simulation_id,
            home_team="HOME",
            away_team="AWAY",
            plays=(
                PlayEvent(
                    1, 1, 1, 800, "HOME", 0, 0, 6, 0, 1, 5, 5,
                    "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE",
                ),
                PlayEvent(
                    2, 2, 2, 600, "HOME", 6, 0, 6, 0, 4, 3, 18,
                    "FIELD_GOAL", 0, 0,
                    score_type="FIELD_GOAL_ATTEMPT_CANDIDATE", kick_distance=35,
                ),
                PlayEvent(
                    3, 3, 4, 200, "HOME", 6, 0, 6, 0, 4, 4, 23,
                    "FIELD_GOAL", 0, 0,
                    score_type="FIELD_GOAL_ATTEMPT_CANDIDATE", kick_distance=40,
                ),
            ),
        )

    def _resolved(self, *, simulation_id, fg_skill):
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        return EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(
                team="HOME",
                kicker_id="H_K",
                kicker_active=True,
                fg_base_skill=fg_skill,
                xp_make_rate=1.0,
                two_point_attempt_rate=0.0,
            ),
            away_profile=SpecialTeamsProfile(
                team="AWAY",
                kicker_id="A_K",
                kicker_active=True,
                fg_base_skill=1.0,
                xp_make_rate=1.0,
            ),
            seed=simulation_id,
        ).resolve(self._raw_path(simulation_id))

    def test_field_goals_made_comes_only_from_engine_c_events(self):
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market

        paths = [self._resolved(simulation_id=1, fg_skill=1.0), self._resolved(simulation_id=2, fg_skill=0.0)]
        result = derive_kicker_stat_market(paths, kicker_id="H_K", stat="field_goals_made", line=1.0)
        self.assertEqual(result, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_extra_points_made_preserves_count_push(self):
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market

        paths = [self._resolved(simulation_id=1, fg_skill=1.0), self._resolved(simulation_id=2, fg_skill=0.0)]
        result = derive_kicker_stat_market(paths, kicker_id="H_K", stat="extra_points_made", line=1.0)
        self.assertEqual(result, {"over": 0.0, "under": 0.0, "push": 1.0})

    def test_kicking_points_are_same_path_fg_plus_xp_points(self):
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market

        paths = [self._resolved(simulation_id=1, fg_skill=1.0), self._resolved(simulation_id=2, fg_skill=0.0)]
        result = derive_kicker_stat_market(paths, kicker_id="H_K", stat="kicking_points", line=4.0)
        self.assertEqual(result, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_longest_field_goal_uses_made_kicks_only_with_zero_none_state(self):
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market

        paths = [self._resolved(simulation_id=1, fg_skill=1.0), self._resolved(simulation_id=2, fg_skill=0.0)]
        result = derive_kicker_stat_market(paths, kicker_id="H_K", stat="longest_field_goal", line=20.0)
        self.assertEqual(result, {"over": 0.5, "under": 0.5, "push": 0.0})

    def test_unknown_kicker_fails_closed_instead_of_returning_zero(self):
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market

        with self.assertRaisesRegex(ValueError, "KICKER_NOT_BOUND_TO_PATH"):
            derive_kicker_stat_market(
                [self._resolved(simulation_id=1, fg_skill=1.0)],
                kicker_id="NOPE",
                stat="field_goals_made",
                line=0.5,
            )

    def test_unresolved_bound_kicker_blocks_even_if_path_has_no_kick_opportunity(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        raw = FootballPlayPath("NFL_EMPTY", 1, "HOME", "AWAY", ())
        resolved = EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(team="HOME", kicker_id="H_K", kicker_active=None),
            away_profile=SpecialTeamsProfile(team="AWAY", kicker_id="A_K", kicker_active=True),
            seed=4,
        ).resolve(raw)
        with self.assertRaisesRegex(ValueError, "KICKER_STATUS_UNRESOLVED:H_K"):
            derive_kicker_stat_market(
                [resolved], kicker_id="H_K", stat="kicking_points", line=0.5
            )

    def test_unsupported_stat_and_cross_game_mix_fail_closed(self):
        from sportsedge.core.simulate.kicker_markets import derive_kicker_stat_market

        path = self._resolved(simulation_id=1, fg_skill=1.0)
        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_KICKER_STAT"):
            derive_kicker_stat_market([path], kicker_id="H_K", stat="fantasy_points", line=7.5)


if __name__ == "__main__":
    unittest.main()
