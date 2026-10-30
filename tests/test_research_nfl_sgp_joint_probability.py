from __future__ import annotations

import unittest

from sportsedge.sports.nfl.sgp_joint_probability import (
    NFLJointProbabilityError,
    enrich_sgp_candidates_with_joint_probability,
    evaluate_leg,
    joint_probability_from_paths,
)


def _path(
    *,
    home_score: int,
    away_score: int,
    rice_tds: int,
    warren_rec: int,
    game_id: str = "IND@KC",
) -> dict:
    return {
        "game_id": game_id,
        "home_team": "KC",
        "away_team": "IND",
        "home_score": home_score,
        "away_score": away_score,
        "players": {
            "Rashee Rice": {
                "player_name": "Rashee Rice",
                "touchdowns": rice_tds,
                "receptions": 6,
            },
            "Tyler Warren": {
                "player_name": "Tyler Warren",
                "receptions": warren_rec,
                "receiving_yards": 39,
            },
        },
    }


LEGS = [
    {"game_id": "IND@KC", "market": "spread", "team": "KC", "line": -6},
    {
        "game_id": "IND@KC",
        "market": "anytime_td",
        "player": "Rashee Rice",
        "side": "Yes",
    },
    {
        "game_id": "IND@KC",
        "market": "receptions",
        "player": "Tyler Warren",
        "side": "Under",
        "line": 4.5,
    },
]


class NFLJointProbabilityTests(unittest.TestCase):
    def test_kc_minus_six_rice_td_warren_under_same_path_joint(self):
        paths = [
            _path(home_score=31, away_score=14, rice_tds=1, warren_rec=4),
            _path(home_score=28, away_score=20, rice_tds=1, warren_rec=5),
            _path(home_score=27, away_score=21, rice_tds=1, warren_rec=4),
            _path(home_score=24, away_score=20, rice_tds=0, warren_rec=3),
        ]
        result = joint_probability_from_paths(paths, LEGS)

        self.assertEqual(result["method"], "SAME_SIMULATION_PATHS")
        self.assertFalse(result["independence_assumption"])
        self.assertEqual(result["resolved_paths"], 4)
        self.assertEqual(result["full_win_paths"], 1)
        self.assertEqual(result["push_paths"], 1)
        self.assertEqual(result["loss_paths"], 2)
        self.assertAlmostEqual(result["joint_model_probability"], 0.25)
        self.assertAlmostEqual(result["marginals"][0]["win_probability"], 0.50)
        self.assertAlmostEqual(result["marginals"][1]["win_probability"], 0.75)
        self.assertAlmostEqual(result["marginals"][2]["win_probability"], 0.75)

    def test_integer_spread_push_is_not_counted_as_parlay_win(self):
        path = _path(home_score=27, away_score=21, rice_tds=1, warren_rec=4)
        spread = evaluate_leg(path, LEGS[0])
        self.assertEqual(spread.result, "PUSH")
        result = joint_probability_from_paths([path], LEGS)
        self.assertEqual(result["full_win_paths"], 0)
        self.assertEqual(result["push_paths"], 1)
        self.assertEqual(result["joint_model_probability"], 0.0)

    def test_moneyline_total_team_total_and_player_markets(self):
        path = _path(home_score=31, away_score=14, rice_tds=1, warren_rec=4)
        path["players"]["Patrick Mahomes"] = {
            "passing_yards": 245,
            "passing_tds": 2,
            "interceptions": 1,
            "rush_attempts": 3,
            "rushing_yards": 12,
        }
        path["players"]["Jonathan Taylor"] = {
            "rushing_yards": 88,
            "receiving_yards": 22,
        }

        checks = [
            {"market": "moneyline", "team": "KC"},
            {"market": "total", "side": "UNDER", "line": 46.5},
            {"market": "team_total", "team": "IND", "side": "UNDER", "line": 19.5},
            {"market": "passing_yards", "player": "Patrick Mahomes", "side": "OVER", "line": 220.5},
            {"market": "pass_tds", "player": "Patrick Mahomes", "side": "OVER", "line": 1.5},
            {"market": "interceptions", "player": "Patrick Mahomes", "side": "OVER", "line": 0.5},
            {"market": "rush_attempts", "player": "Patrick Mahomes", "side": "UNDER", "line": 3.5},
            {"market": "rush_rec_yards", "player": "Jonathan Taylor", "side": "OVER", "line": 101.5},
        ]
        self.assertTrue(all(evaluate_leg(path, leg).result == "WIN" for leg in checks))

    def test_strict_mode_fails_closed_on_missing_player_path(self):
        path = _path(home_score=31, away_score=14, rice_tds=1, warren_rec=4)
        del path["players"]["Tyler Warren"]
        with self.assertRaisesRegex(NFLJointProbabilityError, "NFL_SGP_UNRESOLVED_PATH"):
            joint_probability_from_paths([path], LEGS)

    def test_non_strict_mode_reports_unresolved_without_zero_filling(self):
        complete = _path(home_score=31, away_score=14, rice_tds=1, warren_rec=4)
        missing = _path(home_score=28, away_score=20, rice_tds=1, warren_rec=4)
        del missing["players"]["Tyler Warren"]
        result = joint_probability_from_paths([complete, missing], LEGS, strict=False)
        self.assertEqual(result["resolved_paths"], 1)
        self.assertEqual(result["unresolved_paths"], 1)
        self.assertAlmostEqual(result["resolved_fraction"], 0.5)
        self.assertAlmostEqual(result["joint_model_probability"], 1.0)

    def test_game_mismatch_is_rejected(self):
        paths = [_path(home_score=31, away_score=14, rice_tds=1, warren_rec=4)]
        bad_legs = [dict(LEGS[0], game_id="OTHER@GAME"), LEGS[1], LEGS[2]]
        with self.assertRaisesRegex(NFLJointProbabilityError, "MULTIPLE_LEG_GAMES"):
            joint_probability_from_paths(paths, bad_legs)

    def test_candidate_enrichment_produces_joint_p_for_promo_ranker(self):
        paths = [
            _path(home_score=31, away_score=14, rice_tds=1, warren_rec=4),
            _path(home_score=28, away_score=20, rice_tds=1, warren_rec=5),
            _path(home_score=24, away_score=20, rice_tds=0, warren_rec=3),
        ]
        candidates = [
            {
                "candidate_id": "dk-kc6-rice-warren",
                "game_id": "IND@KC",
                "american_odds": +400,
                "legs": LEGS,
            }
        ]
        enriched = enrich_sgp_candidates_with_joint_probability(candidates, paths)
        self.assertEqual(len(enriched), 1)
        self.assertAlmostEqual(enriched[0]["joint_model_probability"], 1 / 3)
        self.assertEqual(enriched[0]["joint_probability_method"], "SAME_SIMULATION_PATHS")
        self.assertFalse(
            enriched[0]["joint_probability_diagnostics"]["independence_assumption"]
        )


if __name__ == "__main__":
    unittest.main()
