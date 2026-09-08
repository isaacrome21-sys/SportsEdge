import unittest
from datetime import datetime, timezone

from sportsedge.devig import DevigError, multiplicative_devig

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


def quote(side, odds, *, line=8.5, book="draftkings", market="TOTALS", entity="777"):
    row = {
        "game_id": "777",
        "event_id": "777",
        "game_number": 1,
        "period": "FG",
        "market": market,
        "entity_id": str(entity),
        "line": line,
        "side": side,
        "american_odds": odds,
        "book_key": book,
        "retrieved_at": NOW,
        "is_alternate": False,
        "event_home_team_id": "20",
        "event_away_team_id": "10",
    }
    if market in {"MONEYLINE", "RUN_LINE"}:
        row["team_id"] = str(entity)
    return row


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
        with self.assertRaisesRegex(DevigError, "book_key"):
            multiplicative_devig(quote("OVER", -110), quote("UNDER", -110, book="fanduel"))

    def test_pair_requires_complementary_sides(self):
        with self.assertRaisesRegex(DevigError, "SAME_SIDE|complement"):
            multiplicative_devig(quote("OVER", -110), quote("OVER", -110))

    def test_moneyline_opposing_team_entities_are_valid_pair(self):
        home = quote("HOME", -120, line=0.0, market="MONEYLINE", entity="20")
        away = quote("AWAY", +110, line=0.0, market="MONEYLINE", entity="10")
        d = multiplicative_devig(home, away)
        self.assertAlmostEqual(d.candidate_fair_probability + d.opposite_fair_probability, 1.0)

    def test_runline_opposite_signed_entities_are_valid_pair(self):
        home = quote("HOME", +105, line=-1.5, market="RUN_LINE", entity="20")
        away = quote("AWAY", -125, line=+1.5, market="RUN_LINE", entity="10")
        d = multiplicative_devig(home, away)
        self.assertAlmostEqual(d.candidate_fair_probability + d.opposite_fair_probability, 1.0)


if __name__ == "__main__":
    unittest.main()
