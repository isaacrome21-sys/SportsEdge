import unittest

from sportsedge.devig import DevigError, multiplicative_devig


def quote(side, odds, *, line=8.5, book="draftkings", market="TOTALS", entity_id="777"):
    return {
        "game_id": "777",
        "period": "FG",
        "market": market,
        "entity_id": entity_id,
        "line": line,
        "side": side,
        "american_odds": odds,
        "book_key": book,
        "is_alternate": False,
    }


class DevigTests(unittest.TestCase):
    def test_multiplicative_devig_matches_hand_calculated_values(self):
        over = quote("OVER", -113)
        under = quote("UNDER", 104)
        d = multiplicative_devig(over, under)

        q_over = 113 / 213
        q_under = 100 / 204
        expected_over = q_over / (q_over + q_under)
        expected_under = q_under / (q_over + q_under)

        self.assertAlmostEqual(d.candidate_raw_implied, q_over, places=12)
        self.assertAlmostEqual(d.opposite_raw_implied, q_under, places=12)
        self.assertAlmostEqual(d.candidate_fair_probability, expected_over, places=12)
        self.assertAlmostEqual(d.opposite_fair_probability, expected_under, places=12)
        self.assertAlmostEqual(d.candidate_fair_probability + d.opposite_fair_probability, 1.0, places=12)
        self.assertAlmostEqual(d.overround, q_over + q_under - 1.0, places=12)
        self.assertLess(d.candidate_fair_probability, d.candidate_raw_implied)

    def test_pair_requires_same_market_identity(self):
        with self.assertRaisesRegex(DevigError, "identity mismatch"):
            multiplicative_devig(quote("OVER", -110), quote("UNDER", -110, book="fanduel"))

    def test_pair_requires_complementary_sides(self):
        with self.assertRaisesRegex(DevigError, "not complementary"):
            multiplicative_devig(quote("OVER", -110), quote("OVER", -110))

    def test_moneyline_pairs_opposing_team_entities(self):
        multiplicative_devig(
            quote("HOME", -120, line=0.0, market="MONEYLINE", entity_id="10"),
            quote("AWAY", 105, line=0.0, market="MONEYLINE", entity_id="20"),
        )

    def test_moneyline_same_team_entity_rejected(self):
        with self.assertRaisesRegex(DevigError, "opposing team"):
            multiplicative_devig(
                quote("HOME", -120, line=0.0, market="MONEYLINE", entity_id="10"),
                quote("AWAY", 105, line=0.0, market="MONEYLINE", entity_id="10"),
            )

    def test_runline_opposite_signed_pair_passes(self):
        multiplicative_devig(
            quote("HOME", 140, line=-1.5, market="RUN_LINE", entity_id="10"),
            quote("AWAY", -160, line=1.5, market="RUN_LINE", entity_id="20"),
        )

    def test_runline_same_signed_pair_rejected(self):
        with self.assertRaisesRegex(DevigError, "opposite signed"):
            multiplicative_devig(
                quote("HOME", 140, line=-1.5, market="RUN_LINE", entity_id="10"),
                quote("AWAY", -160, line=-1.5, market="RUN_LINE", entity_id="20"),
            )

    def test_totals_still_require_same_entity(self):
        with self.assertRaisesRegex(DevigError, "entity mismatch"):
            multiplicative_devig(
                quote("OVER", -110, entity_id="777"),
                quote("UNDER", -110, entity_id="888"),
            )


if __name__ == "__main__":
    unittest.main()
