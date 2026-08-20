import unittest

from sportsedge.core.simulate.football import (
    DrivePlaySimulator,
    PlayOutcome,
    StarterPullRule,
)


class SequencePolicy:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.states = []

    def __call__(self, state):
        self.states.append(state)
        if self.outcomes:
            return self.outcomes.pop(0)
        return PlayOutcome(play_type="KNEEL", yards=0, elapsed_seconds=max(1, state.seconds_remaining_game))


class FootballDrivePlaySimulatorTests(unittest.TestCase):
    def test_down_distance_field_position_and_clock_feed_each_next_play(self):
        policy = SequencePolicy(
            [
                PlayOutcome(play_type="RUSH", yards=4, elapsed_seconds=30, rusher_id="RB1"),
                PlayOutcome(play_type="PASS", yards=7, elapsed_seconds=25, passer_id="QB1", receiver_id="WR1", target=1, reception=1),
                PlayOutcome(play_type="RUSH", yards=89, elapsed_seconds=20, points=7, rusher_id="RB1"),
            ]
        )
        sim = DrivePlaySimulator(policy=policy, game_seconds=75)
        path = sim.simulate_path(home_team="HOME", away_team="AWAY", initial_possession="HOME")

        self.assertEqual(policy.states[0].down, 1)
        self.assertEqual(policy.states[0].distance, 10)
        self.assertEqual(policy.states[0].yardline_100, 75)
        self.assertEqual(policy.states[1].down, 2)
        self.assertEqual(policy.states[1].distance, 6)
        self.assertEqual(policy.states[1].yardline_100, 71)
        self.assertEqual(policy.states[2].down, 1)
        self.assertEqual(policy.states[2].distance, 10)
        self.assertEqual(policy.states[2].yardline_100, 64)
        self.assertEqual(path.home_score, 7)
        self.assertEqual(path.team_rushing_yards["HOME"], 93)
        self.assertEqual(path.team_passing_yards["HOME"], 7)

    def test_cfb_starter_pull_is_a_path_state_not_a_player_prop_adjustment(self):
        policy = SequencePolicy(
            [
                PlayOutcome(play_type="OTHER", yards=0, elapsed_seconds=1, points=35),
                PlayOutcome(play_type="KNEEL", yards=0, elapsed_seconds=9),
            ]
        )
        sim = DrivePlaySimulator(
            policy=policy,
            game_seconds=10,
            starter_pull_rule=StarterPullRule(min_lead=28, max_seconds_remaining=9),
        )
        sim.simulate_path(home_team="HOME", away_team="AWAY", initial_possession="HOME")

        self.assertTrue(policy.states[0].starters_active)
        self.assertFalse(policy.states[1].starters_active)


if __name__ == "__main__":
    unittest.main()
