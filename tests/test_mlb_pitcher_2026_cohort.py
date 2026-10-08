import unittest
from datetime import date,timedelta
from scripts.eval_mlb_pitcher_2026_cohort import (
    select_2025_leaders,restrict_2026_evaluations,
)
from scripts.eval_mlb_pitcher_window_blend import evaluate


class BroadCohortTest(unittest.TestCase):
    def test_fixed_preseason_leader_order(self):
        raw={"leagueLeaders":[{"leaderCategory":"inningsPitched",
              "leaders":[{"person":{"id":i+101,"fullName":f"Pitcher {i}"}}
                         for i in range(10)]}]}
        selected=select_2025_leaders(raw,5)
        self.assertEqual([p["pitcher_id"] for p in selected],[101,102,103,104,105])
        self.assertEqual([p["2025_ip_rank"] for p in selected],[1,2,3,4,5])

    def test_missing_ranked_population_fails_closed(self):
        with self.assertRaises(ValueError):
            select_2025_leaders({"leagueLeaders":[]},30)

    def test_holdout_restricts_2025_rows_and_preserves_2026(self):
        d=date(2025,7,1)
        starts=[]
        for i in range(80):
            starts.append({"date":(d+timedelta(days=i*4)).isoformat(),
                "row":{"outs":12+i%9,"strikeouts":i%7,"earned_runs":i%3,
                    "hits_allowed":3+i%6,"walks_allowed":i%3}})
        full=evaluate(starts)
        filt=restrict_2026_evaluations(full,"2026-01-01")
        self.assertTrue(all(r["date"][:4]=="2026" for r in filt["records"]) or filt["records"]==[])
        self.assertEqual(filt["overall"],None if not filt["records"] else filt["overall"])


if __name__=="__main__":
    unittest.main()
