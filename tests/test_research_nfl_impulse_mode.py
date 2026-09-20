from __future__ import annotations

import unittest

from sportsedge.sports.nfl.impulse_mode import (
    ProfitBoostTerms,
    american_profit_per_dollar,
    build_impulse_board,
    evaluate_profit_boost_sgp,
    offered_ev_per_dollar,
    profit_multiple_to_american,
    rank_profit_boost_sgps,
)


def _row(
    *,
    player: str,
    model_p: float,
    odds: float,
    fresh: bool = True,
    official: bool = False,
) -> dict:
    return {
        "sport": "NFL",
        "game_id": "IND@KC",
        "provider_market": "player_receptions",
        "market": "receptions",
        "player_id": player.lower().replace(" ", "-"),
        "player_name": player,
        "team": "KC",
        "side": "OVER",
        "line": 3.5,
        "american_odds": odds,
        "model_p": model_p,
        "push_p": 0.0,
        "quote_fresh": fresh,
        "official_eligible": official,
        "bet_status": "OFFICIAL" if official else "BLOCKED",
        "reason": "ALL_GATES_PASS" if official else "TRUTH_GATE_BLOCKED",
    }


class NFLImpulseModeTests(unittest.TestCase):
    def test_offered_ev_uses_model_probability_and_actual_price(self):
        self.assertAlmostEqual(american_profit_per_dollar(+110), 1.10)
        self.assertAlmostEqual(american_profit_per_dollar(-200), 0.50)
        self.assertAlmostEqual(offered_ev_per_dollar(0.60, +110), 0.26)
        self.assertEqual(profit_multiple_to_american(1.5), 150)
        self.assertEqual(profit_multiple_to_american(0.75), -133)

    def test_impulse_board_ignores_official_and_truth_gate_filters(self):
        blocked_but_positive = _row(
            player="Blocked Positive",
            model_p=0.60,
            odds=+110,
            official=False,
        )
        official_lower_ev = _row(
            player="Official Lower EV",
            model_p=0.54,
            odds=+100,
            official=True,
        )
        negative = _row(
            player="Negative",
            model_p=0.45,
            odds=+100,
            official=False,
        )
        payload = {
            "sport": "NFL",
            "results": [official_lower_ev, negative, blocked_but_positive],
        }

        board = build_impulse_board(payload)
        names = [row["player_name"] for row in board["rows"]]
        self.assertEqual(names, ["Blocked Positive", "Official Lower EV"])
        top = board["rows"][0]
        self.assertFalse(top["official_eligible"])
        self.assertEqual(top["bet_status"], "BLOCKED")
        self.assertTrue(top["truth_gate_ignored_for_impulse_selection"])
        self.assertTrue(top["official_status_unchanged"])
        self.assertEqual(top["impulse_grade"], "SMASH")
        self.assertAlmostEqual(top["impulse_offered_ev_per_dollar"], 0.26)
        self.assertFalse(board["authority"]["requires_truth_gate"])
        self.assertFalse(board["authority"]["requires_official_p"])

    def test_impulse_board_defaults_to_fresh_positive_ev_only(self):
        stale = _row(player="Stale", model_p=0.70, odds=+100, fresh=False)
        negative = _row(player="Negative", model_p=0.40, odds=+100)
        positive = _row(player="Positive", model_p=0.55, odds=+100)
        payload = {"sport": "NFL", "results": [stale, negative, positive]}

        board = build_impulse_board(payload)
        self.assertEqual([row["player_name"] for row in board["rows"]], ["Positive"])

        wide = build_impulse_board(
            payload,
            include_stale=True,
            include_negative_ev=True,
            min_ev=-1.0,
        )
        self.assertEqual(len(wide["rows"]), 3)

    def test_profit_boost_changes_break_even_and_ev(self):
        result = evaluate_profit_boost_sgp(
            joint_model_probability=0.45,
            sgp_american_odds=+100,
            leg_count=3,
            wager=25.0,
            terms=ProfitBoostTerms(
                boost_rate=0.50,
                max_wager=25.0,
                min_legs=3,
                min_total_american_odds=-200,
                sgp_only=True,
                eligible_game="IND@KC",
            ),
            same_game=True,
            game_id="IND@KC",
        )
        self.assertTrue(result["eligible"])
        self.assertAlmostEqual(result["boosted_profit_per_dollar"], 1.5)
        self.assertAlmostEqual(result["boosted_break_even_probability"], 0.40)
        self.assertAlmostEqual(result["boosted_ev_per_dollar"], 0.125)
        self.assertEqual(result["boosted_effective_american"], 150)
        self.assertEqual(result["status"], "PLAY")

    def test_minus_200_is_eligible_but_minus_250_is_not(self):
        at_floor = evaluate_profit_boost_sgp(
            joint_model_probability=0.60,
            sgp_american_odds=-200,
            leg_count=3,
            wager=40.0,
        )
        self.assertTrue(at_floor["eligible"])
        self.assertEqual(at_floor["applied_wager"], 25.0)
        self.assertAlmostEqual(at_floor["boosted_break_even_probability"], 1 / 1.75)

        too_short = evaluate_profit_boost_sgp(
            joint_model_probability=0.70,
            sgp_american_odds=-250,
            leg_count=3,
            wager=25.0,
        )
        self.assertFalse(too_short["eligible"])
        self.assertIn("MIN_TOTAL_ODDS_NOT_MET", too_short["eligibility_reasons"])
        self.assertEqual(too_short["status"], "PASS")

    def test_joint_probability_is_required_for_sgp_ev(self):
        result = evaluate_profit_boost_sgp(
            joint_model_probability=None,
            sgp_american_odds=+180,
            leg_count=3,
            wager=25.0,
        )
        self.assertEqual(result["status"], "JOINT_MODEL_P_REQUIRED")
        self.assertIsNone(result["boosted_ev_per_dollar"])
        self.assertEqual(
            result["correlation_rule"],
            "JOINT_MODEL_P_REQUIRED_DO_NOT_MULTIPLY_LEG_PROBABILITIES",
        )

    def test_rank_boost_sgps_uses_joint_ev(self):
        candidates = [
            {
                "candidate_id": "a",
                "game_id": "IND@KC",
                "leg_count": 3,
                "american_odds": +150,
                "joint_model_probability": 0.38,
                "legs": ["L1", "L2", "L3"],
            },
            {
                "candidate_id": "b",
                "game_id": "IND@KC",
                "leg_count": 3,
                "american_odds": +150,
                "joint_model_probability": 0.46,
                "legs": ["L4", "L5", "L6"],
            },
        ]
        ranked = rank_profit_boost_sgps(candidates)
        self.assertEqual([row["candidate_id"] for row in ranked], ["b", "a"])
        self.assertGreater(
            ranked[0]["boosted_ev_per_dollar"], ranked[1]["boosted_ev_per_dollar"]
        )


if __name__ == "__main__":
    unittest.main()
