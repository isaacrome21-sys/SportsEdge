import unittest


class NFLOvertimeDefenseEventTests(unittest.TestCase):
    def _regulation(self):
        from sportsedge.core.simulate.drive_play import FootballPlayPath, PlayEvent
        from sportsedge.core.simulate.special_teams import EngineCSpecialTeamsResolver, SpecialTeamsProfile

        raw = FootballPlayPath(
            "NFL_OT_DEF",
            1,
            "HOME",
            "AWAY",
            (
                PlayEvent(1, 1, 1, 700, "HOME", 0, 0, 6, 0, 1, 5, 5, "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE"),
                PlayEvent(2, 2, 4, 100, "AWAY", 6, 0, 6, 6, 1, 5, 5, "RUSH", 5, 6, score_type="TOUCHDOWN_CANDIDATE"),
            ),
        )
        return EngineCSpecialTeamsResolver(
            home_profile=SpecialTeamsProfile(team="HOME", kicker_id="H_K", kicker_active=True, fg_base_skill=1.0, xp_make_rate=1.0, two_point_attempt_rate=0.0),
            away_profile=SpecialTeamsProfile(team="AWAY", kicker_id="A_K", kicker_active=True, fg_base_skill=1.0, xp_make_rate=1.0, two_point_attempt_rate=0.0),
            seed=11,
        ).resolve(raw)

    def _sack_profile(self):
        from sportsedge.core.simulate.drive_play import TeamDriveProfile

        return TeamDriveProfile(
            pass_rate=1.0,
            completion_rate=1.0,
            success_rate=0.0,
            explosive_rate=0.0,
            turnover_rate=0.0,
            sack_rate=1.0,
            field_goal_attempt_rate=0.0,
            pace_seconds_mean=20.0,
        )

    def test_ot_sacks_are_engine_a_plays_not_incomplete_passes(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator

        simulator = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._sack_profile(),
            away_profile=self._sack_profile(),
            seed=6,
        )
        opportunity, plays, _ = simulator._simulate_opportunity(
            opportunity_index=1,
            team="HOME",
            clock_remaining=600,
            prior_opportunities=[],
            next_play_index=1,
        )
        sacks = [play for play in plays if play.play_type == "SACK"]
        self.assertTrue(sacks)
        self.assertTrue(all(play.yards < 0 for play in sacks))
        self.assertTrue(all(play.pass_complete is None for play in sacks))
        self.assertEqual(opportunity.outcome_type, "KICKOFF_SAFETY")

    def test_opening_possession_safety_credits_defense_and_reconciles(self):
        from sportsedge.core.simulate.overtime_simulator import NFLRegularSeasonOTSimulator
        from sportsedge.core.simulate.overtime import settle_nfl_regular_season_overtime

        simulator = NFLRegularSeasonOTSimulator(
            regulation_path=self._regulation(),
            home_profile=self._sack_profile(),
            away_profile=self._sack_profile(),
            seed=6,
        )
        opportunity, plays, _ = simulator._simulate_opportunity(
            opportunity_index=1,
            team="HOME",
            clock_remaining=600,
            prior_opportunities=[],
            next_play_index=1,
        )
        self.assertEqual(opportunity.scoring_team, "AWAY")
        self.assertEqual(opportunity.points, 2)
        self.assertEqual(sum(play.defensive_points for play in plays), 2)
        safety_play = next(play for play in plays if play.defensive_points == 2)
        self.assertEqual(safety_play.defensive_scoring_team, "AWAY")

        settled = settle_nfl_regular_season_overtime(self._regulation(), (opportunity,))
        self.assertEqual(settled.winner, "AWAY")
        self.assertFalse(settled.tie)


if __name__ == "__main__":
    unittest.main()
