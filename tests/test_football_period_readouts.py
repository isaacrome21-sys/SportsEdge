import unittest


class FootballPeriodReadoutTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "home_score": 27,
                "away_score": 24,
                "q1_home_score": 7,
                "q1_away_score": 3,
                "q2_home_score": 3,
                "q2_away_score": 7,
                "q3_home_score": 7,
                "q3_away_score": 7,
                "q4_home_score": 7,
                "q4_away_score": 7,
                "ot_home_score": 3,
                "ot_away_score": 0,
                "first_half_home_score": 10,
                "first_half_away_score": 10,
                "second_half_regulation_home_score": 14,
                "second_half_regulation_away_score": 14,
                "second_half_with_ot_home_score": 17,
                "second_half_with_ot_away_score": 14,
            },
            {
                "home_score": 17,
                "away_score": 20,
                "q1_home_score": 0,
                "q1_away_score": 7,
                "q2_home_score": 10,
                "q2_away_score": 3,
                "q3_home_score": 0,
                "q3_away_score": 3,
                "q4_home_score": 7,
                "q4_away_score": 7,
                "ot_home_score": 0,
                "ot_away_score": 0,
                "first_half_home_score": 10,
                "first_half_away_score": 10,
                "second_half_regulation_home_score": 7,
                "second_half_regulation_away_score": 10,
                "second_half_with_ot_home_score": 7,
                "second_half_with_ot_away_score": 10,
            },
        ]

    def test_second_half_requires_explicit_ot_settlement_rule(self):
        from sportsedge.core.simulate.markets import derive_period_markets

        with self.assertRaisesRegex(ValueError, "SECOND_HALF_OT_RULE_REQUIRED"):
            derive_period_markets(self.rows, period="second_half")

    def test_second_half_ot_rule_changes_only_the_shared_path_slice(self):
        from sportsedge.core.simulate.markets import derive_period_markets

        regulation = derive_period_markets(
            self.rows, period="second_half", include_ot=False, spread_line=0.0, total_line=28.0
        )
        with_ot = derive_period_markets(
            self.rows, period="second_half", include_ot=True, spread_line=0.0, total_line=28.0
        )
        self.assertEqual(regulation["moneyline"]["home_win"], 0.0)
        self.assertEqual(regulation["moneyline"]["tie"], 0.5)
        self.assertEqual(with_ot["moneyline"]["home_win"], 0.5)
        self.assertEqual(with_ot["moneyline"]["tie"], 0.0)

    def test_quarter_readouts_use_quarter_only_scores(self):
        from sportsedge.core.simulate.markets import derive_period_markets

        q1 = derive_period_markets(self.rows, period="q1", spread_line=0.0, total_line=10.0)
        self.assertEqual(q1["moneyline"]["home_win"], 0.5)
        self.assertEqual(q1["moneyline"]["away_win"], 0.5)
        self.assertEqual(q1["total"]["push"], 0.5)
        self.assertEqual(q1["total"]["under"], 0.5)

    def test_invalid_period_fails_closed(self):
        from sportsedge.core.simulate.markets import derive_period_markets

        with self.assertRaisesRegex(ValueError, "UNSUPPORTED_FOOTBALL_PERIOD"):
            derive_period_markets(self.rows, period="q5")

    def test_alternate_lines_are_predicates_over_same_final_scores(self):
        from sportsedge.core.simulate.markets import derive_alternate_markets

        priced = derive_alternate_markets(
            self.rows,
            spread_lines=(-3.5, -2.5, 2.5),
            total_lines=(40.5, 51.5),
        )
        self.assertEqual(priced["alternate_spread"][-3.5]["home_cover"], 0.0)
        self.assertEqual(priced["alternate_spread"][-2.5]["home_cover"], 0.5)
        self.assertEqual(priced["alternate_spread"][2.5]["home_cover"], 0.5)
        self.assertEqual(priced["alternate_total"][40.5]["over"], 0.5)
        self.assertEqual(priced["alternate_total"][51.5]["under"], 1.0)

    def test_engine_a_rows_expose_unambiguous_second_half_slices(self):
        from sportsedge.core.simulate.football_path import EngineAPathSimulator

        row = EngineAPathSimulator(
            game_id="NFL_TEST",
            home_team="HOME",
            away_team="AWAY",
            expected_home_points=24.0,
            expected_away_points=21.0,
            seed=20260824,
        ).simulate(1)[0].to_market_row()
        self.assertEqual(
            row["second_half_regulation_home_score"],
            row["q3_home_score"] + row["q4_home_score"],
        )
        self.assertEqual(
            row["second_half_with_ot_home_score"],
            row["q3_home_score"] + row["q4_home_score"] + row["ot_home_score"],
        )


if __name__ == "__main__":
    unittest.main()
