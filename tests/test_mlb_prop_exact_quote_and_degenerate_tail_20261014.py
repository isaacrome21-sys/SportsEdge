"""Oct-14 RUN IT regression: real paired quote identity and empirical HR tail refusals.

Tests do not backfill quotes, manufacture a complementary milestone side,
promote a model or change the registry/deployment policy.
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sportsedge.quoted_count_threshold import same_quoted_count_threshold
from sportsedge.research_model_adapters import mlb_batter_to_bridge_rows
from sportsedge.mlb_phone_batter_pricing import phone_batter_rows

NOW = datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)
AS_OF = NOW.isoformat()
SOURCE_AT = (NOW - timedelta(minutes=30)).isoformat()
KICKOFF = (NOW + timedelta(hours=2)).isoformat()
PAST = [(NOW - timedelta(days=11 - i)).isoformat() for i in range(10)]


def _history(homer_flags):
    return [{"plate_appearances": 4, "home_runs": int(flag)}
            for flag in homer_flags]


def _batter_bridge(*, side, line, flags):
    return mlb_batter_to_bridge_rows(
        game_id="20261014-MIL-LAD-3", player_id="batter1",
        market="BATTER_HRS", side=side, line=line,
        features={"pa_history": _history(flags)},
        prior_game_times_utc=PAST, source_as_of_utc=SOURCE_AT,
        as_of_utc=AS_OF, kickoff_utc=KICKOFF,
        home_team="Los Angeles Dodgers", away_team="Milwaukee Brewers",
    )[0]


class ExactThresholdTests(unittest.TestCase):
    def test_same_count_line_across_json_numeric_encodings(self):
        for a, b in ((5.5, "5.5"), ("5.50", 5.5), (6, "6.0"),
                     ("0.50", 0.5)):
            self.assertTrue(same_quoted_count_threshold(a, b), (a, b))

    def test_never_join_rungs_or_malformed_thresholds(self):
        pairs = [(5.5, 6.5), ("5.5", "5.50001"), (True, 1),
                 (None, 5.5), ({}, 5.5), ("nan", 5.5),
                 ("inf", 5.5), ("x", 5.5)]
        for a, b in pairs:
            self.assertFalse(same_quoted_count_threshold(a, b), (a, b))


class EmpiricalTailTests(unittest.TestCase):
    def test_zero_observed_homers_is_named_unvalidated_tail_not_mass_error(self):
        for side in ("OVER", "UNDER"):
            row = _batter_bridge(side=side, line=0.5, flags=[0] * 10)
            self.assertEqual(row["status"], "NO_MODEL_OR_MARKET")
            self.assertEqual(
                row["reason"], "EMPIRICAL_DEGENERATE_TAIL_NO_VALIDATED_MODEL")
            self.assertNotIn("estimate_p", row)

    def test_full_push_mass_remains_a_refusal(self):
        row = _batter_bridge(side="OVER", line=1, flags=[1] * 10)
        self.assertEqual(
            row["reason"], "EMPIRICAL_DEGENERATE_TAIL_NO_VALIDATED_MODEL")

    def test_non_degenerate_history_still_emits_research_probability(self):
        row = _batter_bridge(
            side="OVER", line=0.5, flags=[1] * 4 + [0] * 6)
        self.assertEqual(row["status"], "PRICED_RESEARCH")
        self.assertAlmostEqual(row["estimate_p"], 0.4)
        self.assertFalse(row["official_authority"])


class ExactPairPhoneBridgeTests(unittest.TestCase):
    def setUp(self):
        self.verified = {
            "game_id": "20261014-MIL-LAD-3", "batter_id": "batter1",
            "batter_name": "Test Batter", "lineup_status": "UNCONFIRMED",
            "lineup_verified": False, "prior_game_count": 10,
            "prior_plate_appearances": 40, "source_endpoint": "TEST_VERIFIED",
            "features": {"pa_history": _history([1] * 4 + [0] * 6)},
            "prior_game_times_utc": PAST, "source_as_of_utc": SOURCE_AT,
            "kickoff_utc": KICKOFF,
        }

    def _row(self, side, line):
        return {
            "sport": "MLB", "market": "BATTER_HRS", "player_name": "Test Batter",
            "away": "Milwaukee Brewers", "home": "Los Angeles Dodgers",
            "kickoff": KICKOFF, "side": side, "line": line,
            "odds": -110, "book": "draftkings",
            "quote_captured_at": (NOW - timedelta(seconds=60)).isoformat(),
        }

    def test_independent_over_under_rows_with_string_numeric_lines_match(self):
        rows = [self._row("OVER", "0.50"), self._row("UNDER", 0.5)]
        with patch("sportsedge.mlb_phone_batter_pricing."
                   "MLBBatterPublicSource.prior_games",
                   return_value=self.verified):
            priced, _ = phone_batter_rows(rows, now=NOW)
        self.assertEqual(len(priced), 2)
        for row in priced:
            self.assertIn("model_probability", row)
            self.assertIn("paired_quote_captured_at", row)
            self.assertTrue(row["research_only"])
            self.assertFalse(row["official_authority"])

    def test_ladder_side_stays_unpaired_and_unpriced(self):
        with patch("sportsedge.mlb_phone_batter_pricing."
                   "MLBBatterPublicSource.prior_games",
                   return_value=self.verified):
            priced, _ = phone_batter_rows([self._row("OVER", "0.50")],
                                          now=NOW)
        self.assertEqual(priced[0]["status"], "NO_MODEL_OR_MARKET")
        self.assertEqual(priced[0]["reason"],
                         "EXACT_PAIRED_DK_QUOTE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
