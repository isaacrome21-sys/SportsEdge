from __future__ import annotations

import unittest

from sportsedge.sports.nfl.game_path_probability import (
    NFLGamePathProbabilityError,
    build_game_market_board,
    probability_for_game_leg,
)


def _path(home: int, away: int, *, game_id: str = "IND@KC") -> dict:
    return {
        "game_id": game_id,
        "home_team": "KC",
        "away_team": "IND",
        "home_score": home,
        "away_score": away,
        "players": {},
    }


class NFLGamePathProbabilityTests(unittest.TestCase):
    def test_exact_spread_thresholds_are_not_reused(self):
        paths = [
            _path(27, 21),  # margin 6
            _path(28, 21),  # margin 7
            _path(24, 20),  # margin 4
            _path(31, 14),  # margin 17
        ]
        minus_five_half = probability_for_game_leg(
            paths,
            {"game_id": "IND@KC", "market": "spread", "team": "KC", "line": -5.5},
        )
        minus_six = probability_for_game_leg(
            paths,
            {"game_id": "IND@KC", "market": "spread", "team": "KC", "line": -6},
        )
        self.assertAlmostEqual(minus_five_half["estimate_p"], 0.75)
        self.assertAlmostEqual(minus_five_half["push_probability"], 0.0)
        self.assertAlmostEqual(minus_six["estimate_p"], 0.50)
        self.assertAlmostEqual(minus_six["push_probability"], 0.25)
        self.assertAlmostEqual(minus_six["conditional_win_probability_ex_push"], 2 / 3)
        self.assertNotEqual(minus_five_half["estimate_p"], minus_six["estimate_p"])

    def test_total_and_team_total_use_same_score_paths(self):
        paths = [_path(31, 14), _path(28, 20), _path(24, 17), _path(27, 20)]
        total_under = probability_for_game_leg(
            paths,
            {"game_id": "IND@KC", "market": "total", "side": "UNDER", "line": 46.5},
        )
        ind_under = probability_for_game_leg(
            paths,
            {"game_id": "IND@KC", "market": "team_total", "team": "IND", "side": "UNDER", "line": 19.5},
        )
        self.assertAlmostEqual(total_under["estimate_p"], 0.50)
        self.assertAlmostEqual(ind_under["estimate_p"], 0.75)

    def test_moneyline(self):
        paths = [_path(31, 14), _path(20, 24), _path(27, 27)]
        result = probability_for_game_leg(
            paths,
            {"game_id": "IND@KC", "market": "moneyline", "team": "KC"},
        )
        self.assertAlmostEqual(result["estimate_p"], 1 / 3)
        self.assertAlmostEqual(result["push_probability"], 1 / 3)
        self.assertAlmostEqual(result["conditional_win_probability_ex_push"], 0.5)

    def test_board_evaluates_requested_exact_lines(self):
        paths = [_path(31, 14), _path(27, 21), _path(24, 20)]
        board = build_game_market_board(
            paths,
            [
                {"game_id": "IND@KC", "market": "spread", "team": "KC", "line": -6},
                {"game_id": "IND@KC", "market": "total", "side": "UNDER", "line": 46.5},
                {"game_id": "IND@KC", "market": "team_total", "team": "IND", "side": "UNDER", "line": 19.5},
            ],
        )
        self.assertEqual(board["path_count"], 3)
        self.assertEqual(len(board["rows"]), 3)
        self.assertTrue(all(row["exact_line_required"] for row in board["rows"]))

    def test_market_or_game_mismatch_fails_closed(self):
        paths = [_path(31, 14)]
        with self.assertRaisesRegex(NFLGamePathProbabilityError, "MARKET_UNSUPPORTED"):
            probability_for_game_leg(
                paths,
                {"game_id": "IND@KC", "market": "receptions", "player": "Rashee Rice", "line": 4.5, "side": "OVER"},
            )
        with self.assertRaisesRegex(NFLGamePathProbabilityError, "GAME_ID_MISMATCH"):
            probability_for_game_leg(
                paths,
                {"game_id": "OTHER@GAME", "market": "spread", "team": "KC", "line": -6},
            )


if __name__ == "__main__":
    unittest.main()
