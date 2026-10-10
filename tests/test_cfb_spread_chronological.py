import unittest

from scripts.research_cfb_spread_chronological import (
    BREAKEVEN, THRESHOLD, fit_residual, paired_spreads, grade, study
)


def rows(year,count=80):
    return [{"game_id":f"{year}-{i}","season":year,"model_margin":float(i%9),
             "actual_margin":float((i%7)-3),
             "home_handicap":float(-((i%5)+0.5))}
            for i in range(count)]


class CFBSpreadChronologicalTest(unittest.TestCase):
    def test_fixed_threshold_price(self):
        self.assertEqual(THRESHOLD,0.5)
        self.assertAlmostEqual(BREAKEVEN,110/210)

    def test_fit_fails_without_multi_season_data(self):
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT"):
            fit_residual(rows(2020,500))

    def test_future_seasons_never_enter_fits(self):
        data=[x for year in range(2017,2026) for x in rows(year)]
        report=study(data)
        self.assertGreaterEqual(len(report["folds"]),3)
        for fold in report["folds"]:
            self.assertLess(fold["fit"]["max_train_season"],fold["season"])
        self.assertFalse(report["authority"]["bets"])
        self.assertFalse(report["authority"]["forward_validated"])

    def test_grade_american_odds_excludes_push(self):
        fit={"intercept":0.0,"weight":1.0}
        data=[
            {"model_margin":4.0,"home_handicap":-3.5,"actual_margin":7.0},
            {"model_margin":4.0,"home_handicap":-3.5,"actual_margin":3.0},
            {"model_margin":4.0,"home_handicap":-3.5,"actual_margin":3.5},
        ]
        result=grade(data,fit)
        self.assertEqual((result["wins"],result["losses"],result["pushes"]),(1,1,1))
        self.assertEqual(result["decisions"],2)
        self.assertLess(result["roi_at_assumed_minus_110"],0)

    def test_paired_spreads_require_same_game_and_season(self):
        p={"1":{"season":2023,"model_margin":8,"actual_margin":4}}
        cache={"lines_2023":{"1":{"spread":-3.5},"2":{"spread":-7}}}
        result=paired_spreads(p,cache)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]["home_handicap"],-3.5)
        cache["lines_2023"]["1"]["spread"]=None
        self.assertEqual(paired_spreads(p,cache),[])

    def test_no_proof_when_test_set_small(self):
        report=study(rows(2025,10))
        self.assertEqual(report["status"],"NO_HISTORICALLY_VERIFIED_EDGE")


if __name__=="__main__":
    unittest.main()
