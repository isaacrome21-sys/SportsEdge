import unittest

from scripts.run_mlb_score_compatible_card_final import _build_consistency_card


class TestFinalMLBCardGuard(unittest.TestCase):
    def _row(self, *, market, side, odds, ev, p=.55, push=0.0, team_side=None, pitcher=None):
        return {
            "market_type": market,
            "engine_market": market if market != "GAME_TOTAL" else "TOTALS",
            "side": side,
            "line": 0.0,
            "american_odds": odds,
            "pitcher_name": pitcher,
            "team_side": team_side,
            "research_p": p,
            "push_p": push,
            "settled_research_p": p / (1.0 - push) if push < 1 else 0.0,
            "raw_edge_points": 5.0,
            "ev_per_dollar": ev,
            "simulation_id": "sim-one",
        }

    def test_at_most_one_correlated_game_play(self):
        rows = [
            self._row(market="MONEYLINE", side="HOME", odds=-140, ev=.25),
            self._row(market="RUN_LINE", side="HOME", odds=159, ev=.22),
            self._row(market="TEAM_TOTALS", side="OVER", odds=114, ev=.18, team_side="HOME"),
        ]
        card = _build_consistency_card(rows)
        self.assertEqual(card["primary"]["market_type"], "MONEYLINE")
        self.assertEqual(sum(r["card_status"] == "PRIMARY_RESEARCH_PLAY" for r in card["decisions"]), 1)
        self.assertEqual(
            {r["card_reason"] for r in card["decisions"] if r["card_status"] == "PASS"},
            {"SAME_GAME_CORRELATION_GUARD"},
        )

    def test_pitcher_props_fail_closed_even_with_large_research_ev(self):
        rows = [
            self._row(market="PITCHER_OUTS", side="OVER", odds=107, ev=.50, pitcher="Pitcher A"),
            self._row(market="MONEYLINE", side="HOME", odds=-140, ev=.10),
        ]
        card = _build_consistency_card(rows)
        pitcher = next(r for r in card["decisions"] if r["pitcher_name"])
        self.assertEqual(pitcher["card_status"], "PASS")
        self.assertEqual(pitcher["card_reason"], "PITCHER_DEPENDENCE_NOT_TEMPORALLY_VALIDATED")
        self.assertEqual(card["primary"]["market_type"], "MONEYLINE")

    def test_juice_cap_and_nonpositive_ev_fail_closed(self):
        rows = [
            self._row(market="MONEYLINE", side="HOME", odds=-180, ev=.40),
            self._row(market="RUN_LINE", side="HOME", odds=120, ev=-.01),
        ]
        card = _build_consistency_card(rows)
        self.assertIsNone(card["primary"])
        self.assertEqual(
            {r["card_reason"] for r in card["decisions"]},
            {"STRAIGHT_JUICE_CAP", "NO_POSITIVE_RESEARCH_EV"},
        )

    def test_card_guard_does_not_change_probability_fields(self):
        rows = [
            self._row(market="MONEYLINE", side="HOME", odds=-140, ev=.25, p=.72916),
            self._row(market="GAME_TOTAL", side="OVER", odds=-116, ev=-.0158, p=.46757, push=.11351),
        ]
        original = [(r["research_p"], r["push_p"], r["settled_research_p"], r["ev_per_dollar"]) for r in rows]
        card = _build_consistency_card(rows)
        after = [(r["research_p"], r["push_p"], r["settled_research_p"], r["ev_per_dollar"]) for r in rows]
        self.assertEqual(original, after)
        self.assertEqual(card["primary"]["market_type"], "MONEYLINE")


if __name__ == "__main__":
    unittest.main()
