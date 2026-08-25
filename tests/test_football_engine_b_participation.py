import unittest

from sportsedge.core.simulate.drive_play import EngineADrivePlaySimulator, TeamDriveProfile
from sportsedge.core.simulate.participation import (
    EngineBParticipationSimulator,
    TeamPersonnelProfile,
    aggregate_player_box_scores,
)


class FootballEngineBParticipationTests(unittest.TestCase):
    def _personnel(self, prefix):
        return TeamPersonnelProfile(
            quarterback_id=f"{prefix}_QB",
            rush_shares=((f"{prefix}_RB1", 0.72), (f"{prefix}_RB2", 0.18), (f"{prefix}_QB", 0.10)),
            target_shares=((f"{prefix}_WR1", 0.34), (f"{prefix}_WR2", 0.25), (f"{prefix}_TE1", 0.19), (f"{prefix}_RB1", 0.12), (f"{prefix}_WR3", 0.10)),
        )

    def _path(self):
        return EngineADrivePlaySimulator(
            game_id="NFL_B_TEST",
            home_team="HOME",
            away_team="AWAY",
            home_profile=TeamDriveProfile(pass_rate=0.60, completion_rate=0.67),
            away_profile=TeamDriveProfile(pass_rate=0.55, completion_rate=0.63),
            seed=2026082501,
        ).simulate(1)[0]

    def test_participation_is_identity_bound_to_every_engine_a_play(self):
        path = self._path()
        engine = EngineBParticipationSimulator(
            home_team="HOME", away_team="AWAY",
            home_personnel=self._personnel("H"), away_personnel=self._personnel("A"),
            seed=5150,
        )
        overlay = engine.assign(path)
        self.assertEqual(len(overlay), len(path.plays))
        for play, part in zip(path.plays, overlay):
            self.assertEqual((part.drive_id, part.play_id), (play.drive_id, play.play_id))
            self.assertEqual(part.offense, play.possession)
            if play.play_type == "PASS":
                self.assertIsNotNone(part.quarterback_id)
                self.assertIsNotNone(part.target_id)
                if play.pass_complete:
                    self.assertEqual(part.receiver_id, part.target_id)
                else:
                    self.assertIsNone(part.receiver_id)
            elif play.play_type == "RUSH":
                self.assertIsNotNone(part.rusher_id)

    def test_player_box_scores_reconcile_exactly_to_engine_a_path(self):
        path = self._path()
        overlay = EngineBParticipationSimulator(
            home_team="HOME", away_team="AWAY",
            home_personnel=self._personnel("H"), away_personnel=self._personnel("A"),
            seed=5151,
        ).assign(path)
        boxes = aggregate_player_box_scores(path, overlay)

        self.assertEqual(
            sum(box.pass_attempts for box in boxes.values()),
            sum(play.play_type == "PASS" for play in path.plays),
        )
        self.assertEqual(
            sum(box.completions for box in boxes.values()),
            sum(play.play_type == "PASS" and play.pass_complete is True for play in path.plays),
        )
        self.assertEqual(
            sum(box.passing_yards for box in boxes.values()),
            sum(play.yards for play in path.plays if play.play_type == "PASS" and play.pass_complete is True),
        )
        self.assertEqual(
            sum(box.receiving_yards for box in boxes.values()),
            sum(play.yards for play in path.plays if play.play_type == "PASS" and play.pass_complete is True),
        )
        self.assertEqual(
            sum(box.rushing_yards for box in boxes.values()),
            sum(play.yards for play in path.plays if play.play_type == "RUSH"),
        )
        self.assertEqual(
            sum(box.interceptions_thrown for box in boxes.values()),
            sum(play.turnover_type == "INTERCEPTION" for play in path.plays),
        )
        offensive_touchdowns = sum(play.points == 7 for play in path.plays)
        attributed_touchdowns = sum(box.rushing_tds + box.receiving_tds for box in boxes.values())
        self.assertEqual(attributed_touchdowns, offensive_touchdowns)

    def test_same_path_seed_and_profiles_are_reproducible(self):
        path = self._path()
        kwargs = dict(
            home_team="HOME", away_team="AWAY",
            home_personnel=self._personnel("H"), away_personnel=self._personnel("A"), seed=99,
        )
        self.assertEqual(
            EngineBParticipationSimulator(**kwargs).assign(path),
            EngineBParticipationSimulator(**kwargs).assign(path),
        )

    def test_usage_profiles_fail_closed(self):
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
