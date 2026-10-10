"""Fail-closed independent sportsbook quote research tests."""
import copy
import unittest

from scripts.research_cfb_independent_consensus import evaluate, implied, payout


def card(*, matchup="Away @ Home", market="SPREAD", side="HOME",
         line=-3.5, offered=110, kickoff="2026-10-10T16:00:00Z"):
    return {"schema": "CFB_SDV_CARD_V2",
            "scored_at_utc": "2026-10-10T02:00:00Z",
            "model_status": "MODEL_SDV_PUBLIC_LIVE_UNVALIDATED",
            "results": [{"game_id": "g1", "matchup": matchup,
                         "market": market, "side": side,
                         "line": line, "american_odds": offered,
                         "start_ts": kickoff, "model_p": 0.91,
                         "bet_status": "LEAN"}]}


def references(*, books=("Pinnacle", "Circa"), pair_line=3.5, age="2026-10-10T01:59:00Z",
               away_odds=-110, home_odds=-110):
    return {"books": [
        {"book": b, "captured_at_utc": age, "quotes": [
            {"game_id": "g1", "market": "SPREAD", "side": "AWAY",
             "line": pair_line, "american_odds": away_odds},
            {"game_id": "g1", "market": "SPREAD", "side": "HOME",
             "line": -3.5, "american_odds": home_odds},
        ]} for b in books]}


class ConsensusTest(unittest.TestCase):
    def test_two_independent_pairs_find_research_gap_at_actual_offered_odds(self):
        x = evaluate(card(), references())
        r = x["results"][0]
        self.assertEqual(r["status"], "SHADOW_PRICE_DISLOCATION")
        self.assertAlmostEqual(r["consensus_p"], .5)
        self.assertAlmostEqual(r["consensus_expected_roi"], .05)
        self.assertEqual(r["paired_reference_books"], 2)
        self.assertFalse(x["positive_ev_proven"])
        self.assertFalse(x["bets_enabled"])
        self.assertFalse(x["model_probability_modified"])
        self.assertEqual(x["reference_weight_method"], "EQUAL_BOOK_RESEARCH_NOT_FITTED")

    def test_one_reference_book_fails(self):
        r = evaluate(card(), references(books=("Circa",)))["results"][0]
        self.assertEqual(r["status"], "INSUFFICIENT_INDEPENDENT_BOOKS")
        self.assertIsNone(r["consensus_expected_roi"])

    def test_no_self_reference_from_target_book(self):
        with self.assertRaisesRegex(ValueError, "TARGET_OR_UNNAMED"):
            evaluate(card(), references(books=("DraftKings", "Circa")))

    def test_stale_or_post_card_quotes_are_not_decision_time(self):
        self.assertEqual(evaluate(card(), references(age="2026-10-10T01:00:00Z"))
                         ["results"][0]["status"], "INSUFFICIENT_INDEPENDENT_BOOKS")
        self.assertEqual(evaluate(card(), references(age="2026-10-10T02:01:00Z"))
                         ["results"][0]["status"], "INSUFFICIENT_INDEPENDENT_BOOKS")

    def test_wrong_handicap_must_not_pair(self):
        self.assertEqual(evaluate(card(), references(pair_line=4.0))
                         ["results"][0]["status"], "INSUFFICIENT_INDEPENDENT_BOOKS")

    def test_duplicate_side_rejected(self):
        inp = references()
        inp["books"][0]["quotes"].append(copy.deepcopy(inp["books"][0]["quotes"][0]))
        with self.assertRaisesRegex(ValueError, "DUPLICATE_BOOK_SIDE"):
            evaluate(card(), inp)

    def test_disagreement_blocks_shadows(self):
        inp = references()
        inp["books"][1]["quotes"][0]["american_odds"] = 190
        inp["books"][1]["quotes"][1]["american_odds"] = -250
        self.assertEqual(evaluate(card(), inp)["results"][0]["status"],
                         "REFERENCE_DISAGREEMENT")

    def test_whole_point_quote_requires_push_model_not_false_roi(self):
        c = card(line=-3.0)
        ref = references()
        for book in ref["books"]:
            for q in book["quotes"]:
                q["line"] = -3.0 if q["side"] == "HOME" else 3.0
        r = evaluate(c, ref)["results"][0]
        self.assertEqual(r["paired_reference_books"], 2)
        self.assertEqual(r["status"], "WHOLE_POINT_PUSH_PROBABILITY_UNMODELED")
        self.assertIsNone(r["consensus_expected_roi"])

    def test_impossibly_large_prices_rejected(self):
        with self.assertRaisesRegex(ValueError, "AMERICAN_ODDS_INVALID"):
            evaluate(card(offered=100001), references())

    def test_price_cap_excludes_straight(self):
        r = evaluate(card(offered=-180), references())["results"][0]
        self.assertEqual(r["status"], "PRICE_CAP_MINUS_165")

    def test_illinois_college_excluded(self):
        for team in ["Illinois", "Northwestern", "Northern Illinois", "Illinois State"]:
            with self.subTest(team=team):
                r = evaluate(card(matchup=team + " @ Iowa"), references())["results"][0]
                self.assertEqual(r["status"], "ILLINOIS_COLLEGE_EXCLUDED")

    def test_not_pregame_fails_closed(self):
        r = evaluate(card(kickoff="2026-10-10T01:00:00Z"), references())["results"][0]
        self.assertEqual(r["status"], "NOT_PREGAME")

    def test_raw_model_probability_cannot_change_reference_price(self):
        c = card()
        a = evaluate(c, references())["results"][0]
        c["results"][0]["model_p"] = 0.01
        b = evaluate(c, references())["results"][0]
        self.assertEqual(a["consensus_p"], b["consensus_p"])
        self.assertEqual(a["consensus_expected_roi"], b["consensus_expected_roi"])

    def test_math(self):
        self.assertAlmostEqual(implied(-110), 110/210)
        self.assertAlmostEqual(payout(-110), 100/110)


if __name__ == "__main__":
    unittest.main()
