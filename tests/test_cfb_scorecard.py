import unittest
from sportsedge.sports.cfb.scorecard import build_scorecard, confidence_score, probability_to_american

class TestCFBScorecard(unittest.TestCase):
    def test_fair_odds(self):
        self.assertEqual(probability_to_american(.60), -150)
        self.assertEqual(probability_to_american(.40), 150)

    def test_edge_and_ev_never_feed_score(self):
        a=confidence_score(model_p=.58,fair_market_p=.52,ev_per_dollar=.08)
        b=confidence_score(model_p=.58,fair_market_p=.90,ev_per_dollar=-.75)
        self.assertEqual(a,b)

    def test_model_probability_magnitude_never_feeds_score(self):
        a=confidence_score(model_p=.20,fair_market_p=.52,ev_per_dollar=.08)
        b=confidence_score(model_p=.80,fair_market_p=.52,ev_per_dollar=.08)
        self.assertEqual(a,b)

    def test_stale_quote_collapses_toward_neutral(self):
        fresh=confidence_score(model_p=.60,fair_market_p=.50,ev_per_dollar=.10,quote_age_seconds=0)
        stale=confidence_score(model_p=.60,fair_market_p=.50,ev_per_dollar=.10,quote_age_seconds=180)
        self.assertGreater(fresh,stale)
        self.assertEqual(stale,60.0)

    def test_score_is_not_model_probability(self):
        card=build_scorecard(model_p=.60,fair_market_p=.52,american_odds=-110,edge=.08,ev_per_dollar=.09)
        self.assertEqual(card["model_pct"],60.0)
        self.assertEqual(card["fair_odds"],-150)
        self.assertEqual(card["confidence_semantics"],"QUALITY_SCORE_NOT_WIN_PROBABILITY")
        self.assertNotEqual(card["confidence"],card["model_pct"])

if __name__=="__main__":
    unittest.main()
