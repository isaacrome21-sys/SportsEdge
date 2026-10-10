import unittest
from scripts.run_cfb_crossbook_arb import screen, PRICE_CAP


ASOF="2026-10-09T22:00:00Z"
KICKOFF="2026-10-10T00:00:00Z"


def evt(home="Boise State",away="Fresno State",kind="totals",line=45.5,
        dk_prices=(105,105),other_prices=(105,105),updated=ASOF):
    def items(price):
        if kind=="totals":
            return [{"name":"Over","point":line,"price":price[0]},
                    {"name":"Under","point":line,"price":price[1]}]
        if kind=="spreads":
            return [{"name":home,"point":-line,"price":price[0]},
                    {"name":away,"point":line,"price":price[1]}]
        return [{"name":home,"price":price[0]},
                {"name":away,"price":price[1]}]
    return {
        "id":"game-1","home_team":home,"away_team":away,
        "commence_time":KICKOFF,"bookmakers":[
            {"key":"draftkings","markets":[{"key":kind,"last_update":updated,
                                           "outcomes":items(dk_prices)}]},
            {"key":"fanduel","markets":[{"key":kind,"last_update":updated,
                                        "outcomes":items(other_prices)}]},
        ],
    }


class CFBExactArbTest(unittest.TestCase):
    def test_two_opposing_plus105_books_can_be_mathematically_positive(self):
        result=screen([evt()],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],1)
        opp=result["candidates"][0]
        self.assertEqual(opp["market"],"TOTAL")
        self.assertGreater(opp["theoretical_locked_return_pct"],2)
        self.assertFalse(opp["executable_confirmed"])
        self.assertFalse(result["authority"]["validated_positive_ev_wagers"])
        self.assertAlmostEqual(
            opp["draftkings_leg"]["suggested_stake_per_100"]+
            opp["other_book_leg"]["suggested_stake_per_100"],100,places=2)

    def test_whole_point_total_cannot_claim_guaranteed_positive_return(self):
        # 46 exact game points voids both OVER 46 and UNDER 46. The return
        # on that outcome is 0%, not the advertised +2.5% arbitrage profit.
        result=screen([evt(kind="totals",line=46.0)],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],0)
        self.assertEqual(result["whole_point_push_contracts_skipped"],1)
        self.assertEqual(result["candidates"],[])

    def test_whole_point_spread_cannot_claim_guaranteed_positive_return(self):
        result=screen([evt(kind="spreads",line=3.0)],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],0)
        self.assertEqual(result["whole_point_push_contracts_skipped"],1)
        self.assertFalse(result["authority"]["validated_positive_ev_wagers"])

    def test_half_point_spread_remains_a_candidate_without_push(self):
        result=screen([evt(kind="spreads",line=3.5)],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],1)
        self.assertEqual(result["whole_point_push_contracts_skipped"],0)

    def test_same_book_alone_cannot_create_arb(self):
        event=evt()
        event["bookmakers"]=event["bookmakers"][:1]
        self.assertEqual(screen([event],asof=ASOF)["theoretical_pair_count"],0)

    def test_price_cap_blocks_more_expensive_than_minus165(self):
        event=evt(dk_prices=(-170,+125),other_prices=(+140,-180))
        self.assertEqual(screen([event],asof=ASOF)["theoretical_pair_count"],0)
        self.assertEqual(PRICE_CAP,-165)

    def test_spread_different_threshold_cannot_cross_pair(self):
        event=evt(kind="spreads",line=3.5)
        event["bookmakers"][1]["markets"][0]["outcomes"][0]["point"]=-4.5
        event["bookmakers"][1]["markets"][0]["outcomes"][1]["point"]=+4.5
        self.assertEqual(screen([event],asof=ASOF)["theoretical_pair_count"],0)

    def test_illinois_school_excluded(self):
        for home in ("Illinois","Northwestern","Northern Illinois"):
            with self.subTest(home=home):
                result=screen([evt(home=home)],asof=ASOF)
                self.assertEqual(result["excluded_illinois_events"],1)
                self.assertEqual(result["theoretical_pair_count"],0)

    def test_stale_quotes_block_even_if_both_prices_are_favorable(self):
        result=screen([evt(updated="2026-10-09T21:55:00Z")],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],0)
        self.assertEqual(result["stale_offer_count"],2)

    def test_after_kickoff_never_screen(self):
        result=screen([evt()],asof="2026-10-10T01:00:00Z")
        self.assertEqual(result["theoretical_pair_count"],0)

    def test_h2h_opposite_books_same_game_mathematically_positive(self):
        result=screen([evt(kind="h2h")],asof=ASOF)
        self.assertEqual(result["candidates"][0]["market"],"MONEYLINE")

    def test_invalid_missing_market_timestamps_fail_closed(self):
        event=evt()
        for book in event["bookmakers"]:
            del book["markets"][0]["last_update"]
        result=screen([event],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],0)

    def test_duplicate_offers_within_one_book_block(self):
        event=evt()
        event["bookmakers"][0]["markets"].append(dict(event["bookmakers"][0]["markets"][0]))
        result=screen([event],asof=ASOF)
        self.assertEqual(result["theoretical_pair_count"],0)


if __name__=="__main__":
    unittest.main()
