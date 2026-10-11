"""Regression contracts for independent NFL market-anchored residual pricing.

These are written before the implementation. They must initially fail because
the helper is absent. No model or freeze artifact may be edited.
"""
import unittest
from datetime import datetime, timezone

from sportsedge.sports.nfl.market_residual_research import (
    NFLResidualError, load_fit, anchor_game, price_game_from_pairs,
)

UTC=timezone.utc
OBS="2026-10-11T16:00:00Z"
NOW=datetime(2026,10,11,16,2,tzinfo=UTC)
KICK="2026-10-11T20:25:00Z"


def markets(spread=3.5,total=44.5,stamp=OBS):
    return [
        {"market":"moneyline","line":None,"away_or_over_price":135,
         "home_or_under_price":-155,"quote_retrieved_at":stamp},
        {"market":"spread","line":spread,"away_or_over_price":-110,
         "home_or_under_price":-110,"quote_retrieved_at":stamp},
        {"market":"total","line":total,"away_or_over_price":-110,
         "home_or_under_price":-110,"quote_retrieved_at":stamp},
    ]


class ResidualMarketResearchTests(unittest.TestCase):
    def test_predeclared_shrinkage_pulls_a_20_point_total_bias_toward_market(self):
        fit=load_fit()
        result=anchor_game(raw_margin=12.0, raw_total=64.5,
                           market_margin=3.5, market_total=44.5, fit=fit)
        self.assertLess(abs(result["total"]-44.5),5.0)
        self.assertGreater(result["total"],44.5)
        self.assertLess(abs(result["margin"]-3.5),3.0)
        self.assertAlmostEqual(result["home_mean"]+result["away_mean"],result["total"])
        self.assertAlmostEqual(result["home_mean"]-result["away_mean"],result["margin"])
        self.assertTrue(fit["authority"]["research_only"])
        self.assertFalse(fit["authority"]["promotion"])
        self.assertFalse(fit["authority"]["official"])

    def test_zero_model_residual_cannot_fabricate_edge_due_to_score_shape(self):
        card=price_game_from_pairs(raw_margin=3.5,raw_total=44.5,
                  markets=markets(), observed_at=OBS,as_of=NOW,kickoff_at=KICK)
        self.assertEqual(card["status"],"RESEARCH_ONLY")
        for m in card["markets"]:
            for side in m["sides"]:
                self.assertAlmostEqual(side["edge_probability_points"],0.0,places=8)
                self.assertFalse(side["bet_eligible"])
                self.assertFalse(side["official"])

    def test_missing_one_side_stale_quote_and_nonfinite_predictions_fail_closed(self):
        for invalid in (
            [dict(x) for x in markets()][:-1],
            [dict(x) for x in markets(stamp="2026-10-11T15:00:00Z")],
        ):
            with self.assertRaises(NFLResidualError):
                price_game_from_pairs(raw_margin=3.5,raw_total=44.5,
                    markets=invalid, observed_at=OBS,as_of=NOW,kickoff_at=KICK)
        with self.assertRaises(NFLResidualError):
            price_game_from_pairs(raw_margin=float("nan"),raw_total=44.5,
                 markets=markets(),observed_at=OBS,as_of=NOW,kickoff_at=KICK)
        bad=markets()
        bad[1]=dict(bad[1],home_or_under_price=None)
        with self.assertRaises(NFLResidualError):
            price_game_from_pairs(raw_margin=3.5,raw_total=44.5,markets=bad,
                observed_at=OBS,as_of=NOW,kickoff_at=KICK)

    def test_integer_market_push_mass_is_retained_and_no_promotion_created(self):
        card=price_game_from_pairs(raw_margin=3.0,raw_total=44.0,
                 markets=markets(spread=3.0,total=44.0),
                 observed_at=OBS,as_of=NOW,kickoff_at=KICK)
        by_market={m["market"]:m for m in card["markets"]}
        self.assertGreater(by_market["spread"]["sides"][0]["push_p"],0)
        self.assertGreater(by_market["total"]["sides"][0]["push_p"],0)
        self.assertEqual(card["validated_markets"],[])
        self.assertEqual(card["authority"]["staking"],False)

    def test_no_lookahead_after_kickoff(self):
        with self.assertRaises(NFLResidualError):
            price_game_from_pairs(raw_margin=3.5,raw_total=44.5,
               markets=markets(),observed_at=OBS,as_of=NOW,
               kickoff_at="2026-10-11T15:00:00Z")


if __name__=="__main__":
    unittest.main()
