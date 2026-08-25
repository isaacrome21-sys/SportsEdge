import unittest


class FootballEngineAPathTests(unittest.TestCase):
    def test_every_simulated_path_conserves_quarters_halves_final_margin_and_total(self):
        from sportsedge.core.simulate.football_path import EngineAPathSimulator

        sim = EngineAPathSimulator(
            game_id="NFL_2026_TEST",
            home_team="HOME",
            away_team="AWAY",
            expected_home_points=24.5,
            expected_away_points=21.0,
            seed=20260824,
        )
        paths = sim.simulate(1000)
        self.assertEqual(len(paths), 1000)

        for path in paths:
            row = path.to_market_row()
            self.assertEqual(
                row["first_half_home_score"],
                row["q1_home_score"] + row["q2_home_score"],
            )
            self.assertEqual(
                row["first_half_away_score"],
                row["q1_away_score"] + row["q2_away_score"],
            )
            self.assertEqual(
                row["second_half_home_score"],
                row["q3_home_score"] + row["q4_home_score"] + row["ot_home_score"],
            )
            self.assertEqual(
                row["second_half_away_score"],
                row["q3_away_score"] + row["q4_away_score"] + row["ot_away_score"],
            )
            self.assertEqual(
                row["home_score"],
                row["first_half_home_score"] + row["second_half_home_score"],
            )
            self.assertEqual(
                row["away_score"],
                row["first_half_away_score"] + row["second_half_away_score"],
            )
            self.assertEqual(row["total"], row["home_score"] + row["away_score"])
            self.assertEqual(row["margin"], row["home_score"] - row["away_score"])
            path.assert_conservation()

    def test_scoring_events_are_the_only_source_of_points(self):
        from sportsedge.core.simulate.football_path import EngineAPathSimulator

        path = EngineAPathSimulator(
            game_id="NFL_2026_TEST",
            home_team="HOME",
            away_team="AWAY",
            expected_home_points=27.0,
            expected_away_points=20.0,
            seed=17,
        ).simulate(1)[0]
        row = path.to_market_row()

        home_event_points = sum(event.points for event in path.events if event.team == "HOME")
        away_event_points = sum(event.points for event in path.events if event.team == "AWAY")
        self.assertEqual(home_event_points, row["home_score"])
        self.assertEqual(away_event_points, row["away_score"])

    def test_halves_and_quarters_are_not_independent_market_draws(self):
        from sportsedge.core.simulate.football_path import EngineAPathSimulator
        from sportsedge.core.simulate.markets import derive_game_markets

        rows = [
            path.to_market_row()
            for path in EngineAPathSimulator(
                game_id="NFL_2026_TEST",
                home_team="HOME",
                away_team="AWAY",
                expected_home_points=23.0,
                expected_away_points=22.0,
                seed=33,
            ).simulate(2000)
        ]
        markets = derive_game_markets(
            rows,
            spread_line=0.0,
            total_line=45.5,
            first_half_spread_line=-0.5,
            first_half_total_line=22.5,
        )
        self.assertIn("moneyline", markets)
        self.assertIn("first_half_moneyline", markets)
        for row in rows:
            self.assertEqual(
                row["first_half_home_score"],
                row["q1_home_score"] + row["q2_home_score"],
            )
            self.assertEqual(
                row["first_half_away_score"],
                row["q1_away_score"] + row["q2_away_score"],
            )

    def test_market_blind_inputs_do_not_accept_lines_or_prices(self):
        from sportsedge.core.simulate.football_path import EngineAPathSimulator

        with self.assertRaises(TypeError):
            EngineAPathSimulator(
                game_id="NFL_2026_TEST",
                home_team="HOME",
                away_team="AWAY",
                expected_home_points=24.0,
                expected_away_points=21.0,
                spread_line=-3.0,
                seed=9,
            )

    def test_explicit_seed_is_required(self):
        from sportsedge.core.simulate.football_path import EngineAPathSimulator

        with self.assertRaisesRegex(ValueError, "EXPLICIT_SEED_REQUIRED"):
            EngineAPathSimulator(
                game_id="NFL_2026_TEST",
                home_team="HOME",
                away_team="AWAY",
                expected_home_points=24.0,
                expected_away_points=21.0,
            )


if __name__ == "__main__":
    unittest.main()
