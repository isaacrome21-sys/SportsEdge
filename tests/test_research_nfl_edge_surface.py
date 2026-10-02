from __future__ import annotations

import unittest

from sportsedge.sports.nfl.prop_edge_surface import (
    NFLPropsEdgeError,
    american_implied_probability,
    apply_role_scenario,
    build_props_edge_board,
    compute_prop_score,
    enrich_prop_row,
    probability_to_american,
    prop_row_key,
    settled_model_probability,
    top_prop_picks,
)


def _row(
    *,
    player: str,
    model_p: float,
    fair_market_p: float | None,
    edge: float | None,
    ev: float | None,
    odds: float = 110,
    fresh: bool = True,
    official: bool = False,
) -> dict:
    return {
        "sport": "NFL",
        "game_id": "g1",
        "provider_market": "player_receptions",
        "market": "receptions",
        "player_id": player.lower().replace(" ", "-"),
        "player_name": player,
        "side": "OVER",
        "line": 3.5,
        "american_odds": odds,
        "model_p": model_p,
        "push_p": 0.0,
        "fair_market_p": fair_market_p,
        "edge": edge,
        "ev_per_dollar": ev,
        "quote_fresh": fresh,
        "official_eligible": official,
        "bet_status": "OFFICIAL" if official else "BLOCKED",
        "reason": "ALL_GATES_PASS" if official else "NFL_PROP_PROMOTION_EVIDENCE_REQUIRED",
    }


class NFLPropsEdgeSurfaceTests(unittest.TestCase):
    def test_probability_and_fair_price_match_display_mechanics(self):
        self.assertEqual(probability_to_american(0.595), -147)
        self.assertAlmostEqual(american_implied_probability(-147), 147 / 247)
        self.assertAlmostEqual(settled_model_probability(0.54, 0.10), 0.60)

    def test_all_priced_keeps_negative_edges_and_featured_is_governed(self):
        official = _row(
            player="Deebo Example",
            model_p=0.595,
            fair_market_p=0.442,
            edge=0.153,
            ev=0.22,
            odds=126,
            official=True,
        )
        negative = _row(
            player="Negative Edge",
            model_p=0.48,
            fair_market_p=0.53,
            edge=-0.05,
            ev=-0.03,
            odds=110,
        )
        stale = _row(
            player="Stale Quote",
            model_p=0.60,
            fair_market_p=None,
            edge=None,
            ev=None,
            odds=-110,
            fresh=False,
        )
        payload = {"sport": "NFL", "results": [negative, stale, official]}

        all_priced = build_props_edge_board(payload, view="all_priced")
        self.assertEqual(
            {row["player_name"] for row in all_priced["rows"]},
            {"Deebo Example", "Negative Edge"},
        )
        self.assertEqual(all_priced["summary"]["priced_rows"], 2)
        self.assertAlmostEqual(all_priced["summary"]["best_edge"], 0.153)

        featured = build_props_edge_board(payload, view="featured")
        self.assertEqual([row["player_name"] for row in featured["rows"]], ["Deebo Example"])

        research = build_props_edge_board(payload, view="research_featured")
        self.assertEqual([row["player_name"] for row in research["rows"]], ["Deebo Example"])

        projections = build_props_edge_board(payload, view="all_projections")
        self.assertEqual(len(projections["rows"]), 3)

    def test_one_sided_offer_can_rank_by_ev_without_inventing_novig_edge(self):
        scorer = _row(
            player="Long Shot",
            model_p=0.466,
            fair_market_p=None,
            edge=None,
            ev=0.12,
            odds=204,
            official=True,
        )
        row = enrich_prop_row(scorer)
        self.assertEqual(row["price_state"], "PRICED")
        self.assertIsNone(row["edge_pct"])
        self.assertIsNone(row["market_fair_probability"])

        board = build_props_edge_board(
            {"sport": "NFL", "results": [scorer]},
            view="featured",
            featured_min_ev=0.05,
        )
        self.assertEqual(len(board["rows"]), 1)

    def test_sharp_context_is_display_only_and_does_not_change_score(self):
        base = _row(
            player="Context Test",
            model_p=0.58,
            fair_market_p=0.52,
            edge=0.06,
            ev=0.10,
            odds=115,
        )
        without = enrich_prop_row(base)
        context = {"whale_liquidity": 2700, "signal": "sharp"}
        with_context = enrich_prop_row(base, sharp_context=context)
        self.assertEqual(without["score"], with_context["score"])
        self.assertFalse(with_context["sharp_context"]["promotion_authority"])
        self.assertFalse(with_context["sharp_context"]["used_in_model_probability"])
        self.assertFalse(with_context["sharp_context"]["used_in_score"])

    def test_edge_integrity_fails_closed(self):
        bad = _row(
            player="Mismatch",
            model_p=0.60,
            fair_market_p=0.50,
            edge=0.20,
            ev=0.10,
        )
        with self.assertRaisesRegex(NFLPropsEdgeError, "EDGE_INTEGRITY_MISMATCH"):
            enrich_prop_row(bad)

    def test_score_is_monotone_in_edge_when_other_inputs_match(self):
        lower = compute_prop_score(
            model_probability=0.58,
            edge=0.02,
            ev_per_dollar=0.08,
            quote_fresh=True,
        )
        higher = compute_prop_score(
            model_probability=0.58,
            edge=0.08,
            ev_per_dollar=0.08,
            quote_fresh=True,
        )
        self.assertGreater(higher, lower)

    def test_role_what_if_is_research_only_and_suppresses_model_p(self):
        baseline = {
            **_row(
                player="Receiver",
                model_p=0.60,
                fair_market_p=0.50,
                edge=0.10,
                ev=0.15,
                odds=120,
                official=True,
            ),
            "projection": 43.5,
            "line": 34.5,
        }
        enriched = enrich_prop_row(baseline)
        scenario = apply_role_scenario(
            enriched,
            role_name="targets",
            baseline_role_value=7.1,
            scenario_role_value=8.2,
        )
        self.assertGreater(scenario["projection"], enriched["projection"])
        self.assertFalse(scenario["official_eligible"])
        self.assertEqual(scenario["bet_status"], "RESEARCH_SCENARIO")
        self.assertIsNone(scenario["model_probability"])
        self.assertIsNone(scenario["edge"])
        self.assertFalse(scenario["scenario"]["promotion_authority"])

    def test_top_picks_defaults_to_official_and_research_requires_opt_in(self):
        official = _row(
            player="Official",
            model_p=0.58,
            fair_market_p=0.52,
            edge=0.06,
            ev=0.10,
            official=True,
        )
        blocked = _row(
            player="Research",
            model_p=0.62,
            fair_market_p=0.50,
            edge=0.12,
            ev=0.20,
            official=False,
        )
        payload = {"sport": "NFL", "results": [blocked, official]}

        governed = top_prop_picks(payload)
        self.assertEqual(governed["top_picks_mode"], "GOVERNED_OFFICIAL")
        self.assertEqual([row["player_name"] for row in governed["rows"]], ["Official"])

        research = top_prop_picks(payload, research_only=True)
        self.assertEqual(research["top_picks_mode"], "RESEARCH_ONLY")
        self.assertEqual(
            {row["player_name"] for row in research["rows"]},
            {"Official", "Research"},
        )

    def test_context_key_is_stable(self):
        row = _row(
            player="Key Test",
            model_p=0.55,
            fair_market_p=0.50,
            edge=0.05,
            ev=0.08,
        )
        self.assertEqual(prop_row_key(row), prop_row_key(dict(row)))


if __name__ == "__main__":
    unittest.main()
