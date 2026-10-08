import unittest
from datetime import date,timedelta
from scripts.eval_mlb_pitcher_window_blend import evaluate,marginal,MARKET_LINES


class PitcherWindowBakeoffTest(unittest.TestCase):
    def starts(self, n=40):
        day=date(2026,1,1)
        return [{
            "date":(day+timedelta(days=i)).isoformat(),
            "row":{"outs":12+(i%9),"strikeouts":2+(i%6),
                   "earned_runs":i%4,"hits_allowed":3+(i%5),"walks_allowed":i%3},
        } for i in range(n)]

    def test_six_market_families_and_strictly_prior(self):
        result=evaluate(self.starts())
        self.assertEqual(set(result["markets"]),set(MARKET_LINES))
        self.assertGreater(result["overall"]["scored_rows"],0)
        self.assertTrue(all(r["training_last_date"]<r["date"] for r in result["records"]))
        self.assertEqual(len(set(r["date"] for r in result["records"])),25)

    def test_blended_marginal_shrinks_extreme_recent(self):
        recent=[{"outs":19,"strikeouts":5,"earned_runs":0,
                 "hits_allowed":3,"walks_allowed":0} for _ in range(10)]
        older=[{"outs":10,"strikeouts":1,"earned_runs":4,
                 "hits_allowed":8,"walks_allowed":3} for _ in range(20)]
        a=marginal(recent,"PITCHER_OUTS",12.5)
        b=marginal(recent,"PITCHER_OUTS",12.5,older=older)
        self.assertLess(b,a)
        self.assertGreater(b,0.1)

    def test_same_day_results_not_used(self):
        starts=self.starts()
        starts[16]["date"]=starts[15]["date"]
        result=evaluate(starts)
        self.assertEqual(sum(r["date"] == starts[16]["date"] for r in result["records"]), sum(len(v) for v in MARKET_LINES.values()))
        self.assertTrue(all(r["training_last_date"]<r["date"] for r in result["records"]))

    def test_reject_unsorted(self):
        starts=self.starts()
        starts[10],starts[11]=starts[11],starts[10]
        with self.assertRaises(ValueError):
            evaluate(starts)

if __name__=="__main__":
    unittest.main()
