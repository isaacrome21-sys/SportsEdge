import unittest

from sportsedge.core.simulate.football_path import FootballPathSimulator, TeamPlayProfile
from sportsedge.core.simulate.football_participation import (
    FootballParticipationEngine,
    TeamPersonnelProfile,
    aggregate_player_box_scores,
)


class FootballEngineBParticipationTests(unittest.TestCase):
    def _play_profile(self):
        return TeamPlayProfile(
            pass_rate=0.57,
            completion_rate=0.66,
            sack_rate=0.06,
            interception_rate=0.02,
            fumble_rate=0.01,
            run_yards_mean=4.4,
            run_yards_sd=3.4,
            completion_yards_mean=11.0,
            completion_yards_sd=7.0,
            pace_seconds_mean=27.0,
            field_goal_make_prob=0.83,
        )

    def _personnel(self, prefix):
        return TeamPersonnelProfile(
            quarterback_id=f"{prefix}-QB",
            rush_shares=((f"{prefix}-RB1", 0.72), (f"{prefix}-RB2", 0.18), (f"{prefix}-QB", 0.10)),
            target_shares=((f"{prefix}-WR1", 0.34), (f"{prefix}-WR2", 0.25), (f"{prefix}-TE1", 0.19), (f"{prefix}-RB1", 0.12), (f"{prefix}-WR3", 0.10)),
        )

    def _path(self):
        sim = FootballPathSimulator(
            game_id="engine-b-test",
            home_team="HOME",
            away_team="AWAY",
            home_profile=self._play_profile(),
            away_profile=self._play_profile(),
            seed=8901,
        )
        return sim.simulate(1)[0]

    def test_every_offensive_play_receives_valid_participation_from_same_path(self):
        path = self._path()
        engine = FootballParticipationEngine(
            home_team="HOME",
            away_team="AWAY",
            home_personnel=self._personnel("H"),
            away_personnel=self._personnel("A"),
            seed=441,
        )
        overlay = engine.assign(path)
        self.assertEqual(len(overlay), len(path.plays))
        self.assertEqual([x.play_id for x in overlay], [x.play_id for x in path.plays])
        for play, part in zip(path.plays, overlay):
            self.assertEqual(part.game_id, play.game_id)
            self.assertEqual(part.simulation_id, play.simulation_id)
            self.assertEqual(part.play_id, play.play_id)
            if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION", "SACK"}:
                self.assertIsNotNone(part.quarterback_id)
            if play.play_type in {"PASS_COMPLETE", "PASS_INCOMPLETE", "INTERCEPTION"}:
                self.assertIsNotNone(part.target_id)
            if play.play_type == "PASS_COMPLETE":
                self.assertEqual(part.receiver_id, part.target_id)
            if play.play_type == "RUSH":
                self.assertIsNotNone(part.rusher_id)

    def test_box_scores_reconcile_to_play_path_volume_and_touchdowns(self):
        path = self._path()
        engine = FootballParticipationEngine(
            home_team="HOME", away_team="AWAY",
            home_personnel=self._personnel("H"), away_personnel=self._personnel("A"), seed=442,
        )
        overlay = engine.assign(path)
        boxes = aggregate_player_box_scores(path, overlay)
        team_pass_yards = sum(
            max(0, play.yards) for play in path.plays if play.play_type == "PASS_COMPLETE"
        )
        player_pass_yards = sum(box.passing_yards for box in boxes.values())
        self.assertEqual(player_pass_yards, team_pass_yards)
        team_rush_yards = sum(play.yards for play in path.plays if play.play_type == "RUSH")
        player_rush_yards = sum(box.rushing_yards for box in boxes.values())
        self.assertEqual(player_rush_yards, team_rush_yards)
        offensive_tds = sum(
            play.drive_terminal == "TOUCHDOWN" and play.scoring_team == play.possession
            for play in path.plays
        )
        attributed_tds = sum(box.rushing_tds + box.receiving_tds for box in boxes.values())
        self.assertEqual(attributed_tds, offensive_tds)

    def test_same_seed_and_path_produce_same_assignments(self):
        path = self._path()
        kwargs = dict(
            home_team="HOME", away_team="AWAY",
            home_personnel=self._personnel("H"), away_personnel=self._personnel("A"), seed=99,
        )
        a = FootballParticipationEngine(**kwargs).assign(path)
        b = FootballParticipationEngine(**kwargs).assign(path)
        self.assertEqual(a, b)

    def test_invalid_usage_profile_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "USAGE_SHARES_MUST_SUM_TO_ONE"):
            TeamPersonnelProfile(
                quarterback_id="QB",
                rush_shares=(("RB1", 0.8), ("RB2", 0.3)),
                target_shares=(("WR1", 1.0),),
            )
        with self.assertRaisesRegex(ValueError, "PLAYER_ID_DUPLICATE"):
            TeamPersonnelProfile(
                quarterback_id="QB",
                rush_shares=(("RB1", 0.5), ("RB1", 0.5)),
                target_shares=(("WR1", 1.0),),
            )


if __name__ == "__main__":
    unittest.main()
