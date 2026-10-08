import unittest
from scripts.eval_mlb_pitcher_context_vs_prior import adjusted_over_mass, compare_one


class Index:
    def rel(self, team, season, game_date):
        if game_date.endswith("-13"):
            return 1.3
        return 1.0


class PitcherOpponentAwarePriorTest(unittest.TestCase):
    def _row(self,outs,k,d,opp):
        return {"date":d,"opponent_id":opp,"row":{"outs":outs,"strikeouts":k,
                "earned_runs":1,"hits_allowed":4,"walks_allowed":1}}

    def test_reference_baseline_and_prior_shrink(self):
        hist=[self._row(11,1,f"2025-04-{i:02d}",100) for i in range(1,11)]
        hist += [self._row(19,5,f"2025-05-{i:02d}",101) for i in range(1,11)]
        for market,line in (("PITCHER_OUTS",12.5),("PITCHER_K",2.5)):
            base,candidate=compare_one(hist,index=Index(),market=market,
                line=line,target_opponent=101,target_date="2025-06-01")
            self.assertGreater(base,candidate)
            self.assertGreater(candidate,0.3)
            self.assertLess(candidate,0.8)

    def test_context_mass_applied_to_older_rows(self):
        older=[self._row(12,2,"2025-05-13",111)]
        p=adjusted_over_mass(older,index=Index(),market="PITCHER_OUTS",
                             target_rel=1.0,line=12.5)
        self.assertGreaterEqual(p,0)
        self.assertLessEqual(p,1)

    def test_missing_opponent_fails_closed(self):
        hist=[self._row(16,3,f"2025-04-{i:02d}",101) for i in range(1,21)]
        hist[2]["opponent_id"]=None
        with self.assertRaises((TypeError,ValueError)):
            compare_one(hist,index=Index(),market="PITCHER_K",
                        line=2.5,target_opponent=101,target_date="2025-05-01")


if __name__=="__main__":
    unittest.main()
