import unittest
from datetime import datetime, timezone

from sportsedge.devig import DevigError, multiplicative_devig

NOW = datetime(2026, 9, 8, 2, 0, tzinfo=timezone.utc)


def quote(side, odds, *, line=8.5, book="draftkings"):
    # Legacy fixture form remains supported for non-production historical tests.
    return {
        "game_id": "777", "period": "FG", "market": "TOTALS",
        "entity_id": "777", "line": line, "side": side,
        "american_odds": odds, "book_key": book, "is_alternate": False,
    }


def bound_quote(side, odds, *, line, market, entity, book="draftkings"):
    row = {
        "game_id": "777", "event_id": "777", "game_number": 1,
        "period": "FG", "market": market, "entity_id": str(entity),
        "line": line, "side": side, "american_odds": odds,
        "book_key": book, "retrieved_at": NOW, "is_alternate": False,
        "event_home_team_id": "20", "event_away_team_id": "10",
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
        with self.assertRaisesRegex(DevigError, "identity mismatch"):
            multiplicative_devig(quote("OVER", -110), quote("UNDER", -110, book="fanduel"))

    def test_pair_requires_complementary_sides(self):
        with self.assertRaisesRegex(DevigError, "not complementary"):
            multiplicative_devig(quote("OVER", -110), quote("OVER", -110))

    def test_bound_moneyline_opposing_team_entities_are_valid_pair(self):
        home = bound_quote("HOME", -120, line=0.0, market="MONEYLINE", entity="20")
        away = bound_quote("AWAY", +110, line=0.0, market="MONEYLINE", entity="10")
        d = multiplicative_devig(home, away)
        self.assertAlmostEqual(d.candidate_fair_probability + d.opposite_fair_probability, 1.0)

    def test_bound_runline_opposite_signed_entities_are_valid_pair(self):
        home = bound_quote("HOME", +105, line=-1.5, market="RUN_LINE", entity="20")
        away = bound_quote("AWAY", -125, line=+1.5, market="RUN_LINE", entity="10")
        d = multiplicative_devig(home, away)
        self.assertAlmostEqual(d.candidate_fair_probability + d.opposite_fair_probability, 1.0)

    def test_mixed_bound_and_unbound_pair_rejected(self):
        bound = bound_quote("OVER", -110, line=8.5, market="TOTALS", entity="777")
        with self.assertRaisesRegex(DevigError, "context mismatch"):
            multiplicative_devig(bound, quote("UNDER", -110))


if __name__ == "__main__":
    unittest.main()
