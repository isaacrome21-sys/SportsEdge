import unittest

from scripts.research_cfb_total_chronological import (
    BREAKEVEN_MINUS_110,
    FIRST_RESIDUAL_VALIDATION,
    PRIMARY_THRESHOLD,
    evaluate_season,
    fit_residual,
    paired_rows,
    parse_espn_betting_totals,
    walkforward,
)


def sample(season, count=80, offset=4, outcome=0):
    return [
        {"game_id":f"{season}-{i}", "season":season,
         "model_total":50.0+offset, "closing_total":50.0,
         "realized_total":50.0+outcome}
        for i in range(count)
    ]


class HistoricalCFBTotalResidualTest(unittest.TestCase):
    def test_predeclared_minus110_threshold(self):
        self.assertEqual(PRIMARY_THRESHOLD,2.0)
        self.assertAlmostEqual(BREAKEVEN_MINUS_110,110/210)

    def test_no_borrowing_future_seasons(self):
        data=[]
        for s in range(2017,2026):
            data += sample(s,80,offset=3+0.2*(s-2017),outcome=1)
        report=walkforward(data)
        self.assertGreaterEqual(len(report["per_season"]),3)
        for fold in report["per_season"]:
            self.assertLess(fold["fit"]["max_train_season"],fold["season"])
            self.assertGreaterEqual(fold["season"],FIRST_RESIDUAL_VALIDATION)
        self.assertFalse(report["authority"]["validated_positive_ev"])
        self.assertFalse(report["authority"]["bets"])

    def test_one_season_cannot_calibrate(self):
        with self.assertRaisesRegex(ValueError,"HISTORY_INSUFFICIENT"):
            fit_residual(sample(2020,400))

    def test_zero_predictive_spread_rejected(self):
        train=[]
        for s in (2017,2018,2019,2020):
            train+=sample(s,80,offset=4.0)
        with self.assertRaisesRegex(ValueError,"VARIANCE_ZERO"):
            fit_residual(train)

    def test_holdout_grade_no_push_in_denominator(self):
        rows=[
            {"model_total":54.,"closing_total":50.,"realized_total":52.},
            {"model_total":54.,"closing_total":50.,"realized_total":48.},
            {"model_total":54.,"closing_total":50.,"realized_total":50.},
        ]
        x=evaluate_season(rows,0.0,1.0)
        self.assertEqual((x["wins"],x["losses"],x["pushes"]),(1,1,1))
        self.assertEqual(x["decisions"],2)
        self.assertLess(x["roi_at_assumed_minus_110"],0)

    def test_closes_join_only_exact_id_and_valid_line(self):
        pred={
            "a":{"season":2023,"home_pred":28,"away_pred":24,"home_pts":21,"away_pts":24},
            "b":{"season":2023,"home_pred":28,"away_pred":24,"home_pts":21,"away_pts":24},
        }
        line={"a":{"total":47.5},"b":{"total":None}}
        joined=paired_rows(pred,line)
        self.assertEqual(len(joined),1)
        self.assertEqual(joined[0]["game_id"],"a")
        self.assertEqual(joined[0]["realized_total"],45.0)

    def test_espn_totals_evaluation_only_parser(self):
        raw = (
            b"game_id,season,over_under,game_spread,odds_source\n"
            b"4001,2025,44.5,-3.5,ESPN\n"
            b"4002,2025,,1.5,ESPN\n"
            b"4003,2025,54.5,0,ESPN\n"
        )
        parsed=parse_espn_betting_totals(raw,season=2025)
        self.assertEqual(parsed,{"4001":{"total":44.5},"4003":{"total":54.5}})
        self.assertNotIn("game_spread",parsed["4001"])

    def test_espn_missing_total_column_rejected(self):
        with self.assertRaisesRegex(ValueError,"COLUMNS_MISSING"):
            parse_espn_betting_totals(b"game_id,season,game_spread\n1,2025,-7.5\n",
                                      season=2025)

    def test_espn_duplicate_market_rows_fail_closed(self):
        with self.assertRaisesRegex(ValueError,"DUPLICATE_GAME"):
            parse_espn_betting_totals(
                b"game_id,season,over_under\n1,2025,50\n1,2025,50\n",
                season=2025)

    def test_never_passes_when_historical_coverage_insufficient(self):
        report=walkforward(sample(2025,20))
        self.assertEqual(report["status"],"BLOCKED_NO_HISTORICAL_VALIDATION")
        self.assertEqual(report["pooled"]["decisions"],0)


if __name__=="__main__":
    unittest.main()
