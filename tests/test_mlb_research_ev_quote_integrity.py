import unittest
from scripts.audit_mlb_research_ev_quote_integrity import audit,american_profit


class MLBResearchQuoteEVIntegrityTests(unittest.TestCase):
    def example(self):
        quote={
            "game_id":"A@B","market_type":"GAME_TOTAL","side":"OVER",
            "line":7.0,"price":-117,"paired_side":"UNDER",
            "paired_price":-103,"book":"draftkings","source":"MANUAL",
            "observed_at":"2026-10-07T17:26:26-05:00",
            "first_pitch_at":"2026-10-07T19:00:00-05:00",
        }
        def result(side,price,win,lose):
            return {
                "game_id":"A@B","market_type":"GAME_TOTAL","side":side,
                "line":7,"american_odds":price,"book":"draftkings",
                "observed_at":"2026-10-07T22:26:26+00:00",
                "research_p":win,"push_p":0.14765,"loss_p":lose,
                "ev_per_dollar":win*american_profit(price)-lose,
            }
        return {"official":False,"results":[
            result("OVER",-117,.62127,.23108),
            result("UNDER",-103,.23108,.62127)]},{"rows":[quote]}

    def test_push_ev_payout_not_wrong_no_push_formula(self):
        card,quotes=self.example()
        result=audit(card,quotes)
        self.assertEqual(result["priced_sides"],2)
        self.assertEqual(result["independently_confirmed_quotes"],0)
        self.assertAlmostEqual(result["rows"][0]["recomputed_research_ev"],.29992,places=5)
        self.assertFalse(result["rows"][0]["actionable_from_this_audit"])

    def test_reject_unpaired_snapshot_side(self):
        card,quotes=self.example()
        quotes["rows"][0]["paired_side"]="OVER"
        with self.assertRaises(ValueError):
            audit(card,quotes)


    def test_run_line_pair_must_flip_handicap_sign(self):
        card, quotes = self.example()
        q=quotes["rows"][0]
        q.update({"market_type":"RUN_LINE","side":"AWAY","line":1.5,
                  "price":-157,"paired_side":"HOME","paired_price":130})
        away,home=card["results"]
        away.update({"market_type":"RUN_LINE","side":"AWAY","line":1.5,
                     "american_odds":-157,"research_p":.55,"push_p":0.0,
                     "loss_p":.45,"ev_per_dollar":.55*american_profit(-157)-.45})
        home.update({"market_type":"RUN_LINE","side":"HOME","line":-1.5,
                     "american_odds":130,"research_p":.45,"push_p":0.0,
                     "loss_p":.55,"ev_per_dollar":.45*american_profit(130)-.55})
        report=audit(card,quotes)
        self.assertEqual(report["priced_sides"],2)
        self.assertEqual(report["rows"][1]["line"],-1.5)

    def test_quote_price_mismatch_fails(self):
        card,quotes=self.example()
        card["results"][0]["american_odds"]=-120
        with self.assertRaises(ValueError):
            audit(card,quotes)

    def test_wrong_ev_arithmetic_fails(self):
        card,quotes=self.example()
        card["results"][0]["ev_per_dollar"]+=0.08
        with self.assertRaises(ValueError):
            audit(card,quotes)

    def test_post_first_pitch_snapshot_fails(self):
        card,quotes=self.example()
        quotes["rows"][0]["observed_at"]="2026-10-07T19:15:00-05:00"
        with self.assertRaises(ValueError):
            audit(card,quotes)


if __name__=="__main__":
    unittest.main()
