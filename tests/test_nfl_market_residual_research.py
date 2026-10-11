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

    def test_unified_adapter_feeds_anchor_means_into_frozen_joint_score_grid(self):
        from sportsedge.sports.nfl.residual_unified_adapter import run_residual_unified_research
        out = run_residual_unified_research(
            game_id="2026_05_AWAY_HOME",home_team="HOME",away_team="AWAY",
            raw_margin=10.0,raw_total=66.5,paired_markets=markets(),
            observed_at=OBS,as_of=NOW,kickoff_at=KICK,n_sims=80,seed=7,
        )
        center=out["residual"]["center"]
        self.assertLess(abs(center["total"]-44.5),3.0)
        self.assertAlmostEqual(out["engine"]["score_means"]["mean_home"],center["home_mean"])
        self.assertAlmostEqual(out["engine"]["score_means"]["mean_away"],center["away_mean"])
        self.assertEqual(out["engine"]["score_distribution"]["sampled_paths"],80)
        self.assertTrue(out["authority"]["research_only"])
        self.assertFalse(out["authority"]["promotion"])

    def test_auto_renderer_never_promotes_legacy_absolute_model_leans(self):
        from scripts.render_auto_dk_phone_summary import candidates
        residual=price_game_from_pairs(raw_margin=3.5,raw_total=55.5,
            markets=markets(),observed_at=OBS,as_of=NOW,kickoff_at=KICK)
        payload={"residual_pricing_enabled":True,"games":[{
            "away":"AWAY","home":"HOME","commence_time":KICK,
            "residual_research":residual,
            "markets":[{"market":"total","lean":{
                "selection":"Over","line":44.5,"price_american":-110,
                "estimate_p":0.99,"edge_probability_points":0.49,
                "ev_per_dollar":0.9}}],
        }]}
        rows=candidates("NFL",payload)
        self.assertTrue(all(row["role"]=="LEAN" for row in rows))
        self.assertTrue(all(row["reason"].startswith("RESIDUAL_RESEARCH_ONLY") for row in rows))
        self.assertFalse(any(row["ev"]==0.9 for row in rows))
        self.assertFalse(any(row["price"] is None for row in rows))

    def test_run_it_research_entry_point_keeps_pairing_and_never_emits_bet(self):
        from sportsedge.nfl_run_it import run_it_residual_research, NflRunItError
        def quote(market, selection, line, price):
            return {"game_id":"2026_05_AWAY_HOME","home":"HOME","away":"AWAY",
                    "market":market,"selection":selection,"line":line,
                    "book":"draftkings","retrieved_at":OBS,"price_american":price}
        quotes=[
            quote("moneyline","AWAY",None,135),quote("moneyline","HOME",None,-155),
            quote("spread","AWAY",3.5,-110),quote("spread","HOME",-3.5,-110),
            quote("total","OVER",44.5,-110),quote("total","UNDER",44.5,-110),
        ]
        raw={"2026_05_AWAY_HOME":{"margin":13.5,"total":65.5,"family":"G1_RESEARCH"}}
        kickoff={"2026_05_AWAY_HOME":KICK}
        out=run_it_residual_research(quotes,raw,kickoff,as_of=NOW)
        self.assertEqual(out["validated_markets"],[])
        self.assertFalse(out["authority"]["official"])
        self.assertNotIn("picks",out)
        center=out["games"][0]["research"]["center"]
        self.assertLess(center["total"],50.0)
        self.assertGreater(center["total"],44.5)
        with self.assertRaises(NflRunItError):
            run_it_residual_research(quotes[:-1],raw,kickoff,as_of=NOW)

    def test_no_lookahead_after_kickoff(self):
        with self.assertRaises(NFLResidualError):
            price_game_from_pairs(raw_margin=3.5,raw_total=44.5,
               markets=markets(),observed_at=OBS,as_of=NOW,
               kickoff_at="2026-10-11T15:00:00Z")


if __name__=="__main__":
    unittest.main()
