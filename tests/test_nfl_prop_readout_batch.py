import unittest
from tests import test_football_player_market_readouts as fixtures
from sportsedge.sports.nfl.prop_readout_batch import derive_prop_batch, OFFENSE, KICKER, DEFENSE


class NFLPropBatchTests(unittest.TestCase):
    def paths(self):
        helper = fixtures.FootballPlayerMarketReadoutTests()
        return [helper._attributed(12, 5, 1), helper._attributed(22, 3, 2)]

    def test_generator_reused_and_integer_push_preserved(self):
        report = derive_prop_batch([
            {"market": "player_pass_yds", "player_id": "H_QB", "line": 17},
            {"market": "player_pass_completions", "player_id": "H_QB", "line": 1},
        ], offensive_paths=iter(self.paths()))
        self.assertEqual(report["rows"][0]["research_probabilities"]["over"], .5)
        self.assertEqual(report["rows"][1]["research_probabilities"]["push"], 1)
        self.assertFalse(report["promotion_authority"])

    def test_every_provider_route_retains_missing_input_disposition(self):
        keys = list(OFFENSE) + list(KICKER) + list(DEFENSE) + ["team_sacks", "team_turnovers", "player_first_td", "player_anytime_td", "unknown"]
        rows = derive_prop_batch([{"market": key, "player_id": "P", "team": "H", "line": .5} for key in keys])["rows"]
        self.assertEqual(len(rows), len(keys))
        self.assertTrue(all(row["status"] == "BLOCKED" and row["model_p"] is None for row in rows))
        self.assertIn("COMPLETE_SCORER_PATH", rows[-2]["reason"])

    def test_duplicate_simulations_fail(self):
        p = self.paths()[0]
        with self.assertRaisesRegex(ValueError, "DUPLICATE_SIMULATION"):
            derive_prop_batch([], offensive_paths=[p, p])

    def test_bad_line_does_not_abort_other_markets(self):
        requests = [{"market": "player_pass_yds", "player_id": "H_QB", "line": True},
                    {"market": "player_receptions", "player_id": "H_WR", "line": .5}]
        rows = derive_prop_batch(requests, offensive_paths=self.paths())["rows"]
        self.assertEqual(rows[0]["status"], "BLOCKED")
        self.assertEqual(rows[1]["research_probabilities"]["over"], 1)

    def test_complete_scorer_batch_supports_td_markets(self):
        from tests.test_nfl_touchdown_readouts import path
        paths = [path(1, [(1, 100, "H", "TOUCHDOWN", 6, "WR")])]
        markets = ["player_anytime_td", "player_first_td", "player_last_td", "player_two_plus_td", "player_three_plus_td", "player_tds_over"]
        rows = derive_prop_batch([{"market": m, "player_id": "WR", "team": "H", "line": 1} for m in markets], scorer_paths=paths)["rows"]
        self.assertTrue(all(row["status"] == "RESEARCH_READOUT_NOT_MODEL_P" for row in rows))
        self.assertEqual(rows[0]["research_probabilities"]["yes"], 1)
        self.assertEqual(rows[3]["research_probabilities"]["yes"], 0)
        self.assertEqual(rows[-1]["research_probabilities"]["push"], 1)


if __name__ == "__main__":
    unittest.main()
