"""Test-first contract for market-anchored NFL research game pricing.

No trained NFL residual coefficients are claimed: use preregistered small priors.
All game markets must be priced from market-anchored score distribution deltas,
not the frozen Attempt 9 isotonic mapping on absolute model outputs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import unittest

from sportsedge.sports.nfl.market_anchored_residual import (
    ResidualQuoteError,
    anchor_prediction,
    load_frozen_policy,
    price_game,
)

NOW = datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)


def game(*, spread=3.5, total=50.5, ml=True, timestamp=None):
    observed = (timestamp or NOW).isoformat()
    m = [
        {"market": "spread", "line": spread, "away_or_over_price": -110,
         "home_or_under_price": -110, "quote_retrieved_at": observed},
        {"market": "total", "line": total, "away_or_over_price": -110,
         "home_or_under_price": -110, "quote_retrieved_at": observed},
    ]
    if ml:
        m.append({"market": "moneyline", "line": None,
                  "away_or_over_price": +150,
                  "home_or_under_price": -180, "quote_retrieved_at": observed})
    return {"home": "BAL", "away": "KC",
            "commence_time": (NOW + timedelta(hours=3)).isoformat(),
            "markets": m}


class NflMarketAnchoredResidualTests(unittest.TestCase):
    def test_supplied_policy_cannot_bypass_authority_or_freshness(self):
        for field, value in (("validated_markets", ["total"]),
                             ("max_quote_age_seconds", 1801)):
            cfg = load_frozen_policy()
            cfg[field] = value
            with self.subTest(field=field), self.assertRaises(ResidualQuoteError):
                price_game(game(), raw_model_margin=3.5, raw_model_total=50.5,
                           as_of=NOW, policy=cfg)
        cfg = load_frozen_policy()
        cfg["coefficients"]["total"]["weight"] = 1.0
        with self.assertRaises(ResidualQuoteError):
            anchor_prediction(raw_model_margin=3.5, raw_model_total=70,
                              market_margin=3.5, market_total=50.5, policy=cfg)

    def test_intercept_is_part_of_residual_not_cancelled_by_baseline(self):
        cfg = load_frozen_policy()
        cfg["coefficients"]["total"]["intercept"] = 0.5
        rows = price_game(game(), raw_model_margin=3.5, raw_model_total=50.5,
                          as_of=NOW, policy=cfg)
        over = next(r for r in rows if r["selection"] == "Over")
        self.assertGreater(over["edge_probability_points"], 0)

    def test_cross_market_anchor_clock_skew_fails_closed(self):
        ticket = game()
        ticket["markets"][0]["quote_retrieved_at"] = (NOW-timedelta(seconds=60)).isoformat()
        with self.assertRaisesRegex(ResidualQuoteError, "SKEW"):
            price_game(ticket, raw_model_margin=3.5, raw_model_total=50.5, as_of=NOW)

    def test_precommitted_small_coefficients_and_no_authority(self):
        cfg = load_frozen_policy()
        for name in ("margin", "total"):
            self.assertEqual(cfg["coefficients"][name]["intercept"], 0.0)
            self.assertLessEqual(cfg["coefficients"][name]["weight"], 0.25)
            self.assertGreaterEqual(cfg["coefficients"][name]["weight"], 0.0)
        self.assertFalse(cfg["authority"]["promotion"])
        self.assertFalse(cfg["authority"]["official"])
        self.assertFalse(cfg["authority"]["staking"])
        self.assertEqual(cfg["validated_markets"], [])
        self.assertEqual(cfg["evidence_role"], "RESEARCH_ONLY_UNFITTED_PRIOR")

    def test_biased_total_shrinks_back_to_market_and_means_are_coherent(self):
        a = anchor_prediction(raw_model_margin=11, raw_model_total=68,
                              market_margin=3.5, market_total=47.5)
        self.assertAlmostEqual(a["fair_margin"], 3.5 + 0.15 * (11 - 3.5))
        self.assertAlmostEqual(a["fair_total"], 47.5 + 0.15 * (68 - 47.5))
        self.assertAlmostEqual(a["mean_home"] + a["mean_away"], a["fair_total"])
        self.assertAlmostEqual(a["mean_home"] - a["mean_away"], a["fair_margin"])
        self.assertLess(a["fair_total"], 52)

    def test_zero_residual_has_zero_edge_against_paired_no_vig(self):
        rows = price_game(game(), raw_model_margin=3.5,
                          raw_model_total=50.5, as_of=NOW)
        self.assertEqual(len(rows), 6)  # ML/spread/total, both sides
        self.assertTrue(all(abs(r["edge_probability_points"]) < 1e-9 for r in rows))
        self.assertTrue(all(r["status"] == "RESEARCH_ONLY" for r in rows))
        self.assertTrue(all("model_p" not in r and "official" not in r for r in rows))

    def test_small_residual_does_not_manufacture_a_two_point_edge(self):
        rows = price_game(game(), raw_model_margin=3.6,
                          raw_model_total=50.6, as_of=NOW)
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(abs(r["edge_probability_points"]) < 0.02 for r in rows))

    def test_all_three_markets_are_priced_from_paired_lines(self):
        rows = price_game(game(), raw_model_margin=8.0,
                          raw_model_total=55.0, as_of=NOW)
        self.assertEqual({x["market"] for x in rows}, {"moneyline", "spread", "total"})
        self.assertTrue(all(0 <= x["estimate_p"] <= 1 for x in rows))
        self.assertTrue(all(x["devig_method"] == "POWER_V1" for x in rows))
        self.assertTrue(all(x["joint_score_grid"] for x in rows))

    def test_fail_closed_when_any_reference_market_is_unpaired_stale_or_nonfinite(self):
        unpaired = game()
        unpaired["markets"][0]["home_or_under_price"] = None
        with self.assertRaisesRegex(ResidualQuoteError, "PAIRED"):
            price_game(unpaired, raw_model_margin=2, raw_model_total=50, as_of=NOW)

        stale = game(timestamp=NOW - timedelta(minutes=31))
        with self.assertRaisesRegex(ResidualQuoteError, "STALE"):
            price_game(stale, raw_model_margin=2, raw_model_total=50, as_of=NOW)

        with self.assertRaisesRegex(ResidualQuoteError, "NONFINITE"):
            anchor_prediction(raw_model_margin=math.nan, raw_model_total=50,
                              market_margin=2, market_total=48)

        missing_total = game()
        missing_total["markets"] = [r for r in missing_total["markets"] if r["market"] != "total"]
        with self.assertRaisesRegex(ResidualQuoteError, "SPREAD_TOTAL_REQUIRED"):
            price_game(missing_total, raw_model_margin=2, raw_model_total=50, as_of=NOW)

    def test_no_forward_promotion_on_development_residuals(self):
        row = price_game(game(), raw_model_margin=-5, raw_model_total=70, as_of=NOW)
        self.assertTrue(all(x["eligible_as_bet"] is False for x in row))
        self.assertTrue(all(x["forward_clv_status"] == "PENDING" for x in row))


class NflResidualEntrypointTests(unittest.TestCase):
    def test_run_it_bridge_prices_three_game_markets_without_authority(self):
        from sportsedge.nfl_run_it import run_it_market_anchored
        stamp = NOW.isoformat()
        base = {"game_id": "2026_06_KC_BAL", "away": "KC",
                "home": "BAL", "book": "draftkings", "retrieved_at": stamp}
        quotes = [
            {**base, "market": "moneyline", "selection": "KC", "line": None, "price_american": 150},
            {**base, "market": "moneyline", "selection": "BAL", "line": None, "price_american": -180},
            {**base, "market": "spread", "selection": "KC", "line": 3.5, "price_american": -110},
            {**base, "market": "spread", "selection": "BAL", "line": -3.5, "price_american": -110},
            {**base, "market": "total", "selection": "OVER", "line": 50.5, "price_american": -110},
            {**base, "market": "total", "selection": "UNDER", "line": 50.5, "price_american": -110},
        ]
        raw = {"2026_06_KC_BAL": {"margin": 3.5, "total": 50.5,
               "commence_time": (NOW + timedelta(hours=3)).isoformat()}}
        card = run_it_market_anchored(quotes, raw, as_of=NOW)
        self.assertEqual(card["picks"], [])
        self.assertEqual(card["validated_markets"], [])
        self.assertFalse(card["promotion_authority"])
        self.assertEqual(len(card["games"][0]["market_anchored_research_prices"]), 6)
        self.assertTrue(all(abs(x["edge_probability_points"]) < 1e-9
                            for x in card["games"][0]["market_anchored_research_prices"]))

    def test_unified_cli_research_sidecar_preserves_frozen_game_market_disable(self):
        from scripts.run_nfl_unified_lines_card import attach_residual_game_research
        prior = []
        for i in range(1, 8):
            prior.extend([
                {"date": f"2026-10-{i:02d}", "home": "KC", "away": "LV",
                 "hs": 24, "as": 14},
                {"date": f"2026-10-{i:02d}", "home": "BAL", "away": "CIN",
                 "hs": 28, "as": 17},
            ])
        ticket = {"observed_at": NOW.isoformat(), "slate": "2026-10-11",
                  "games": [game()]}
        payload = {"games": [{"engine": {"game_market_edge_disabled": True}}]}
        result = attach_residual_game_research(payload, ticket, prior)
        self.assertTrue(result["games"][0]["engine"]["game_market_edge_disabled"])
        self.assertEqual(len(result["games"][0]["residual_game_prices"]), 6)
        self.assertEqual(result["residual_research_authority"]["validated_markets"], [])
        self.assertFalse(result["residual_research_authority"]["official"])

    def test_unified_residual_sidecar_uses_frozen_grid_with_adjusted_means(self):
        from sportsedge.sports.nfl.unified_residual_research import run_unified_residual_research
        base = {"game_id": "2026_06_KC_BAL", "home": "BAL", "away": "KC",
                "book": "draftkings", "retrieved_at": NOW.isoformat()}
        quotes = [
            {**base, "market": "moneyline", "selection": "KC", "price_american": 150},
            {**base, "market": "moneyline", "selection": "BAL", "price_american": -180},
            {**base, "market": "spread", "selection": "KC", "line": 3.5, "price_american": -110},
            {**base, "market": "spread", "selection": "BAL", "line": -3.5, "price_american": -110},
            {**base, "market": "total", "selection": "OVER", "line": 50.5, "price_american": -110},
            {**base, "market": "total", "selection": "UNDER", "line": 50.5, "price_american": -110},
        ]
        out = run_unified_residual_research(
            game_id="2026_06_KC_BAL", home_team="BAL", away_team="KC",
            raw_margin=13.5, raw_total=65.5, paired_game_quotes=quotes,
            game_start_ts=(NOW + timedelta(hours=3)).isoformat(),
            as_of=NOW.isoformat(), n_sims=120, seed=11,
            ask_sims_questions=[{"question": "KC wins by 7+", "price_american": 180}])
        self.assertEqual(len(out["asked_sims"]), 1)
        self.assertEqual(out["asked_sims"][0]["sample_count"], 120)
        self.assertEqual(out["asked_sims"][0]["quote_status"], "USER_SUPPLIED_UNVERIFIED")
        self.assertEqual(out["asked_sims"][0]["status"], "RESEARCH_ONLY_NOT_VALIDATED")
        self.assertFalse(out["asked_sims"][0]["eligible_as_bet"])
        fair_margin = 3.5 + 0.15 * (13.5 - 3.5)
        fair_total = 50.5 + 0.15 * (65.5 - 50.5)
        self.assertAlmostEqual(out["score_means"]["mean_home"], (fair_total + fair_margin) / 2)
        self.assertAlmostEqual(out["score_means"]["mean_away"], (fair_total - fair_margin) / 2)
        self.assertEqual(len(out["game_markets"]), 6)
        self.assertEqual(out["picks"], [])
        self.assertEqual(out["validated_markets"], [])
        self.assertFalse(out["authority"]["promotion_authority"])
        self.assertTrue(all(r["status"] == "RESEARCH_ONLY" for r in out["game_markets"]))

    def test_unified_residual_sidecar_requires_paired_quotes(self):
        from sportsedge.sports.nfl.unified_residual_research import (
            UnifiedResidualResearchError, run_unified_residual_research)
        with self.assertRaisesRegex(UnifiedResidualResearchError, "PAIRED_GAME_QUOTES_REQUIRED"):
            run_unified_residual_research(
                game_id="x", home_team="BAL", away_team="KC",
                raw_margin=10, raw_total=48, paired_game_quotes=[],
                game_start_ts=(NOW + timedelta(hours=3)).isoformat(),
                as_of=NOW.isoformat())


if __name__ == "__main__":
    unittest.main()
