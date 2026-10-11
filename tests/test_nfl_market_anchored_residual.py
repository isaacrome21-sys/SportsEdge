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

        stale = game(timestamp=NOW - timedelta(minutes=11))
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


if __name__ == "__main__":
    unittest.main()
