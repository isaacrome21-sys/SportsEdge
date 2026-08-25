import unittest


class NFLOvertimeSpecialTeamsTransitionTests(unittest.TestCase):
    def test_opening_kickoff_transition_can_score_and_counts_as_receivers_opportunity(self):
        from sportsedge.core.simulate.overtime_transitions import NFLRegularSeasonOTTransition

        transition = NFLRegularSeasonOTTransition(
            transition_index=1,
            transition_type="OPENING_KICKOFF_RETURN_TOUCHDOWN",
            from_team="HOME",
            receiving_team="AWAY",
            next_possession_team="AWAY",
            next_yardline_100=None,
            clock_seconds_remaining=594,
            points=6,
            scoring_team="AWAY",
            creates_opportunity=True,
            return_touchdown=True,
        )
        self.assertTrue(transition.creates_opportunity)
        self.assertTrue(transition.return_touchdown)
        self.assertEqual(transition.scoring_team, "AWAY")
        self.assertIsNone(transition.next_yardline_100)

    def test_non_scoring_kickoff_and_punt_require_next_yardline(self):
        from sportsedge.core.simulate.overtime_transitions import NFLRegularSeasonOTTransition

        kickoff = NFLRegularSeasonOTTransition(
            transition_index=1,
            transition_type="OPENING_KICKOFF_RETURN",
            from_team="HOME",
            receiving_team="AWAY",
            next_possession_team="AWAY",
            next_yardline_100=72,
            clock_seconds_remaining=594,
            points=0,
            scoring_team=None,
            creates_opportunity=True,
            return_touchdown=False,
        )
        punt = NFLRegularSeasonOTTransition(
            transition_index=2,
            transition_type="PUNT_RETURN",
            from_team="AWAY",
            receiving_team="HOME",
            next_possession_team="HOME",
            next_yardline_100=61,
            clock_seconds_remaining=420,
            points=0,
            scoring_team=None,
            creates_opportunity=True,
            return_touchdown=False,
        )
        self.assertEqual(kickoff.next_yardline_100, 72)
        self.assertEqual(punt.next_yardline_100, 61)

    def test_scoring_return_cannot_claim_a_next_scrimmage_spot(self):
        from sportsedge.core.simulate.overtime_transitions import NFLRegularSeasonOTTransition

        with self.assertRaisesRegex(ValueError, "OT_SCORING_TRANSITION_HAS_NEXT_YARDLINE"):
            NFLRegularSeasonOTTransition(
                transition_index=1,
                transition_type="PUNT_RETURN_TOUCHDOWN",
                from_team="HOME",
                receiving_team="AWAY",
                next_possession_team="AWAY",
                next_yardline_100=75,
                clock_seconds_remaining=300,
                points=6,
                scoring_team="AWAY",
                creates_opportunity=True,
                return_touchdown=True,
            )

    def test_transition_points_and_team_identity_fail_closed(self):
        from sportsedge.core.simulate.overtime_transitions import NFLRegularSeasonOTTransition

        with self.assertRaisesRegex(ValueError, "OT_TRANSITION_SCORING_TEAM_REQUIRED"):
            NFLRegularSeasonOTTransition(
                transition_index=1,
                transition_type="PUNT_RETURN_TOUCHDOWN",
                from_team="HOME",
                receiving_team="AWAY",
                next_possession_team="AWAY",
                next_yardline_100=None,
                clock_seconds_remaining=300,
                points=6,
                scoring_team=None,
                creates_opportunity=True,
                return_touchdown=True,
            )

    def test_only_receiving_team_can_score_return_touchdown(self):
        from sportsedge.core.simulate.overtime_transitions import NFLRegularSeasonOTTransition

        with self.assertRaisesRegex(ValueError, "OT_RETURN_TOUCHDOWN_SCORER_INVALID"):
            NFLRegularSeasonOTTransition(
                transition_index=1,
                transition_type="PUNT_RETURN_TOUCHDOWN",
                from_team="HOME",
                receiving_team="AWAY",
                next_possession_team="AWAY",
                next_yardline_100=None,
                clock_seconds_remaining=300,
                points=6,
                scoring_team="HOME",
                creates_opportunity=True,
                return_touchdown=True,
            )


if __name__ == "__main__":
    unittest.main()
