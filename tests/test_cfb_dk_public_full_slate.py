"""Deterministic public Saturday DK quote capture tests (synthetic page HTML)."""
import unittest

from scripts.fetch_cfb_dk_public_full_slate import (
    EXPECTED_MATCHUPS, _game_time, compile_full_slate, parse_public_html,
)

PAGE = """
<html><body><h1>DraftKings Sportsbook Betting Splits</h1>
<h4>Indiana @ Nebraska</h4><div>10/10, 12:00PM</div>
<div>Moneyline</div><div>Odds</div><div>% Handle</div><div>% Bets</div>
<div>Nebraska</div><a>+260</a><div>33%</div><div>9%</div>
<div>Indiana</div><a>-325</a><div>67%</div><div>91%</div>
<h5>Spread</h5><div>Odds</div><div>% Handle</div><div>% Bets</div>
<div>Indiana -7.5</div><a>−115</a><div>46%</div><div>59%</div>
<div>Nebraska +7.5</div><a>−105</a><div>54%</div><div>41%</div>
<h5>Total</h5><div>Odds</div><div>% Handle</div><div>% Bets</div>
<div>Over 47.5</div><a>−118</a><div>42%</div><div>83%</div>
<div>Under 47.5</div><a>−102</a><div>58%</div><div>17%</div>
<h4>Ball State @ Northwestern</h4><div>10/10, 12:30PM</div>
<h5>Spread</h5><div>Ball State +35.5</div><a>−108</a>
<div>Northwestern -35.5</div><a>−112</a>
<h5>Total</h5><div>Over 52.5</div><a>−110</a>
<div>Under 52.5</div><a>−110</a></body></html>
"""


class FullSlateCaptureTest(unittest.TestCase):
    def test_exact_schedule_is_full_46(self):
        self.assertEqual(len(EXPECTED_MATCHUPS), 46)
        self.assertEqual(len(set(EXPECTED_MATCHUPS)), 46)

    def test_public_two_way_prices_and_kickoff_are_literal(self):
        rows = parse_public_html(PAGE, page=1)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["spread"], [-7.5, -115, -105])
        self.assertEqual(rows[0]["total"], [47.5, -118, -102])
        self.assertEqual(rows[0]["start_ts"], "2026-10-10T16:00:00+00:00")

    def test_only_eligible_game_enters_model_board(self):
        result = compile_full_slate({1: PAGE}, captured_at_utc="2026-10-10T02:00:00Z",
                                    min_eligible_paired=1)
        self.assertEqual(len(result["board"]), 1)
        self.assertEqual(result["board"][0]["away"], "Indiana")
        self.assertFalse(result["board"][0]["sportsbook_price_receipt_verified"])
        self.assertEqual(len(result["inventory"]), 46)
        self.assertEqual(next(x["status"] for x in result["inventory"]
                              if x["home"] == "Northwestern"), "ILLINOIS_COLLEGE_EXCLUDED")

    def test_fail_closed_for_unpaired_total(self):
        text = PAGE.replace("<div>Under 47.5</div>", "<div>Under 48.5</div>")
        result = compile_full_slate({1: text}, captured_at_utc="2026-10-10T02:00:00Z",
                                    min_eligible_paired=0)
        self.assertEqual(len(result["board"]), 0)
        self.assertEqual(next(x["status"] for x in result["inventory"]
                              if x["away"] == "Indiana"), "MISSING_PAIRED_SPREAD_OR_TOTAL")

    def test_reject_conflicting_pagination(self):
        changed = PAGE.replace("Over 47.5", "Over 47.0").replace("Under 47.5", "Under 47.0")
        result = compile_full_slate({1: PAGE, 2: changed}, min_eligible_paired=0)
        self.assertEqual(len(result["board"]), 0)
        self.assertEqual(next(x["status"] for x in result["inventory"]
                              if x["away"] == "Indiana"), "CONFLICTING_PUBLIC_PAGE_QUOTES")

    def test_wrong_day_is_rejected(self):
        self.assertIsNone(_game_time("10/9, 08:00PM"))
        result = compile_full_slate({1: PAGE.replace("10/10, 12:00PM", "10/9, 12:00PM")},
                                    min_eligible_paired=0)
        self.assertEqual(len(result["board"]), 0)

    def test_never_guesses_opposite_price(self):
        bad = PAGE.replace("<div>Nebraska +7.5</div><a>−105</a>", "")
        rows = parse_public_html(bad, page=1)
        self.assertIsNone(rows[0]["spread"])
        result = compile_full_slate({1: bad}, min_eligible_paired=0)
        self.assertEqual(len(result["board"]), 0)

    def test_required_coverage_not_a_partial_success(self):
        with self.assertRaisesRegex(ValueError, "INSUFFICIENT_PAIRED_COVERAGE"):
            compile_full_slate({1: PAGE}, min_eligible_paired=30)


if __name__ == "__main__":
    unittest.main()
