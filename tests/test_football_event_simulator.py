import unittest

from sportsedge.core.simulate.football import (
    FootballGamePath,
    PlayEvent,
    read_event_game_markets,
    validate_event_path_conservation,
)


class FootballEventSimulatorTests(unittest.TestCase):
    def test_periods_halves_and_final_reconcile_from_same_plays(self):
        plays = (
            PlayEvent(period=1, offense="HOME", points=7),
            PlayEvent(period=1, offense="AWAY", points=3),
            PlayEvent(period=2, offense="HOME", points=3),
            PlayEvent(period=2, offense="AWAY", points=7),
            PlayEvent(period=3, offense="HOME", points=7),
            PlayEvent(period=4, offense="AWAY", points=3),
        )
        path = FootballGamePath.from_plays(home_team="HOME", away_team="AWAY", plays=plays)
        validate_event_path_conservation(path)

        self.assertEqual(path.home_quarter_points, (7, 3, 7, 0))
        self.assertEqual(path.away_quarter_points, (3, 7, 0, 3))
        self.assertEqual(path.first_half_score, (10, 10))
        self.assertEqual(path.final_score, (17, 13))
        self.assertEqual(sum(path.home_quarter_points), path.home_score)
        self.assertEqual(sum(path.away_quarter_points), path.away_score)

        markets = read_event_game_markets((path,))
        self.assertEqual(markets.final_margin_pmf, {4: 1.0})
        self.assertEqual(markets.final_total_pmf, {30: 1.0})
        self.assertEqual(markets.first_half_margin_pmf, {0: 1.0})
        self.assertEqual(markets.first_half_total_pmf, {20: 1.0})
        self.assertEqual(markets.quarter_total_pmfs[0], {10: 1.0})

    def test_player_yards_reconcile_to_team_yards_and_receptions_do_not_exceed_targets(self):
        plays = (
            PlayEvent(period=1, offense="HOME", play_type="PASS", passer_id="QB1", receiver_id="WR1", passing_yards=12, target=1, reception=1),
            PlayEvent(period=1, offense="HOME", play_type="PASS", passer_id="QB1", receiver_id="WR2", passing_yards=8, target=1, reception=1),
            PlayEvent(period=1, offense="HOME", play_type="PASS", passer_id="QB1", receiver_id="WR1", passing_yards=0, target=1, reception=0),
            PlayEvent(period=2, offense="HOME", play_type="RUSH", rusher_id="RB1", rushing_yards=9),
            PlayEvent(period=2, offense="HOME", play_type="RUSH", rusher_id="QB1", rushing_yards=4),
        )
        path = FootballGamePath.from_plays(home_team="HOME", away_team="AWAY", plays=plays)
        validate_event_path_conservation(path)

        self.assertEqual(path.team_passing_yards["HOME"], 20)
        self.assertEqual(sum(path.player_receiving_yards.values()), 20)
        self.assertEqual(path.team_rushing_yards["HOME"], 13)
        self.assertEqual(sum(path.player_rushing_yards.values()), 13)
        self.assertEqual(path.player_targets["WR1"], 2)
        self.assertEqual(path.player_receptions["WR1"], 1)

    def test_receptions_greater_than_targets_is_rejected(self):
        with self.assertRaises(ValueError):
            FootballGamePath.from_plays(
                home_team="HOME",
                away_team="AWAY",
                plays=(
                    PlayEvent(period=1, offense="HOME", play_type="PASS", passer_id="QB1", receiver_id="WR1", passing_yards=5, target=0, reception=1),
                ),
            )


if __name__ == "__main__":
    unittest.main()
