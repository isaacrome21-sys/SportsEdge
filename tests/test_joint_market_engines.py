import unittest

from sportsedge.hitter_joint_engine import price_hitter_market, HitterJointEngineError
from sportsedge.pitcher_joint_engine import price_pitcher_market, PitcherJointEngineError


def hrow(pa, s, d, t, hr, rbi, runs, sb, bb, k):
    hits = s + d + t + hr
    return {
        "plate_appearances": pa, "hits": hits, "singles": s, "doubles": d, "triples": t,
        "home_runs": hr, "total_bases": s + 2*d + 3*t + 4*hr, "rbi": rbi,
        "runs": runs, "stolen_bases": sb, "walks": bb, "strikeouts": k,
        "extra_base_hits": d + t + hr,
    }


class HitterJointCoherenceTests(unittest.TestCase):
    POOL = [
        hrow(4,1,0,0,0,0,1,0,1,1), hrow(4,1,0,0,1,3,2,0,0,0),
        hrow(5,0,0,0,0,0,0,0,1,2), hrow(4,0,1,0,0,1,0,0,0,1),
        hrow(4,2,1,0,0,2,1,1,0,0), hrow(4,0,0,0,1,4,1,0,0,2),
        hrow(5,2,0,0,0,0,1,0,1,1), hrow(4,0,0,0,0,1,0,0,1,2),
        hrow(4,1,1,0,0,1,2,1,0,1), hrow(4,1,0,0,0,0,0,0,2,1),
    ]

    def _base(self, market, line=0.5, side="OVER"):
        return {"game_id":"g1","market":market,"entity_id":"b1","line":line,"side":side,"feature_source_hash":"a"*64,"features":{"history_pool":self.POOL}}

    def test_one_plus_hit_equals_total_bases_over_half(self):
        self.assertAlmostEqual(price_hitter_market(self._base("HITS"))["model_p"], price_hitter_market(self._base("TOTAL_BASES"))["model_p"], places=12)

    def test_home_run_and_xbh_are_subsets_of_hit(self):
        hr=price_hitter_market(self._base("HOME_RUNS"))["model_p"]; xbh=price_hitter_market(self._base("EXTRA_BASE_HITS"))["model_p"]; hit=price_hitter_market(self._base("HITS"))["model_p"]
        self.assertLessEqual(hr,xbh); self.assertLessEqual(xbh,hit)

    def test_combo_is_exact_arithmetic_on_same_rows(self):
        result=price_hitter_market(self._base("HITS_RUNS_RBIS",line=2.5))["model_p"]
        expected=sum((r["hits"]+r["runs"]+r["rbi"])>2.5 for r in self.POOL)/len(self.POOL)
        self.assertAlmostEqual(result,expected)

    def test_multi_rbi_game_is_supported(self):
        result=price_hitter_market(self._base("RBI",line=2.5))["model_p"]
        self.assertAlmostEqual(result,sum(r["rbi"]>2.5 for r in self.POOL)/len(self.POOL))

    def test_hit_type_markets_share_same_rows(self):
        singles=price_hitter_market(self._base("SINGLES"))["model_p"]
        self.assertAlmostEqual(singles,sum(r["singles"]>0.5 for r in self.POOL)/len(self.POOL))
        ks=price_hitter_market(self._base("BATTER_K"))["model_p"]
        self.assertAlmostEqual(ks,sum(r["strikeouts"]>0.5 for r in self.POOL)/len(self.POOL))

    def test_quote_side_does_not_change_model_identity(self):
        self.assertEqual(price_hitter_market(self._base("HITS",side="OVER"))["model_input_hash"],price_hitter_market(self._base("HITS",side="UNDER"))["model_input_hash"])

    def test_integer_push_conserves_probability(self):
        over=price_hitter_market(self._base("HITS",line=1.0,side="OVER")); under=price_hitter_market(self._base("HITS",line=1.0,side="UNDER"))
        self.assertAlmostEqual(over["model_p"]+under["model_p"]+over["push_p"],1.0)

    def test_incoherent_history_row_fails_closed(self):
        bad=list(self.POOL); bad[0]={**bad[0],"home_runs":2}
        model=self._base("HITS"); model["features"]={"history_pool":bad}
        with self.assertRaises(HitterJointEngineError): price_hitter_market(model)


class PitcherJointCoherenceTests(unittest.TestCase):
    POOL=[
        {"strikeouts":5,"outs":15,"earned_runs":2,"hits_allowed":5,"walks_allowed":2},
        {"strikeouts":7,"outs":18,"earned_runs":1,"hits_allowed":4,"walks_allowed":1},
        {"strikeouts":8,"outs":19,"earned_runs":3,"hits_allowed":6,"walks_allowed":2},
        {"strikeouts":6,"outs":21,"earned_runs":0,"hits_allowed":3,"walks_allowed":3},
        {"strikeouts":9,"outs":20,"earned_runs":4,"hits_allowed":7,"walks_allowed":1},
    ]
    def _base(self,market,line,side="OVER"):
        return {"game_id":"g1","market":market,"entity_id":"p1","line":line,"side":side,"feature_source_hash":"b"*64,"features":{"history_pool":self.POOL}}
    def test_outs_support_is_physically_bounded(self): self.assertEqual(price_pitcher_market(self._base("PITCHER_OUTS",27.0))["model_p"],0.0)
    def test_combined_pitcher_prop_uses_same_rows(self):
        result=price_pitcher_market(self._base("PITCHER_HITS_WALKS_ER",8.5))["model_p"]
        expected=sum((r["hits_allowed"]+r["walks_allowed"]+r["earned_runs"])>8.5 for r in self.POOL)/len(self.POOL)
        self.assertAlmostEqual(result,expected)
    def test_invalid_historical_outs_fail_closed(self):
        bad=list(self.POOL); bad[0]={**bad[0],"outs":28}; model=self._base("PITCHER_OUTS",17.5); model["features"]={"history_pool":bad}
        with self.assertRaises(PitcherJointEngineError): price_pitcher_market(model)
    def test_integer_push_conserves_probability(self):
        over=price_pitcher_market(self._base("PITCHER_ER",2.0,"OVER")); under=price_pitcher_market(self._base("PITCHER_ER",2.0,"UNDER"))
        self.assertAlmostEqual(over["model_p"]+under["model_p"]+over["push_p"],1.0)


if __name__=="__main__": unittest.main()
