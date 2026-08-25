import json
from pathlib import Path
import unittest

from sportsedge.additional_mlb_odds_source import CANONICAL_MARKETS as ADDITIONAL_MARKETS
from sportsedge.draftkings_prop_source import COUNT_MARKETS
from sportsedge.quote_bridge import SUPPORTED_MARKETS
from sportsedge.team_total_odds_source import TEAM_TOTAL_PROVIDER_MARKET


FEATURED_GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS"})
TEAM_TOTAL_MARKETS = frozenset({"TEAM_TOTALS"})
UNMAPPED_NORMALIZED_MARKETS = frozenset({"F5_TEAM_TOTALS"})


class MLBQuoteSourceCoverageTests(unittest.TestCase):
    def test_declared_source_capability_covers_every_acquirable_canonical_market(self):
        count = frozenset(COUNT_MARKETS)
        additional = frozenset(ADDITIONAL_MARKETS)
        team_totals = TEAM_TOTAL_MARKETS
        groups = (count, additional, FEATURED_GAME_MARKETS, team_totals)
        for i, left in enumerate(groups):
            for right in groups[i + 1:]:
                self.assertFalse(left & right)

        self.assertEqual(TEAM_TOTAL_PROVIDER_MARKET, "team_totals")
        source_capability = count | FEATURED_GAME_MARKETS | additional | team_totals
        normalized = set(SUPPORTED_MARKETS)
        self.assertEqual(source_capability, normalized - set(UNMAPPED_NORMALIZED_MARKETS))
        self.assertEqual(normalized - source_capability, set(UNMAPPED_NORMALIZED_MARKETS))
        self.assertEqual(len(source_capability), 37)
        self.assertEqual(len(normalized), 38)

    def test_f5_team_totals_gap_is_explicit_and_fail_closed(self):
        surface = json.loads(Path("config/mlb_market_surface.json").read_text(encoding="utf-8"))
        rows = {row["market"]: row for row in surface["markets"]}
        team = rows["TEAM_TOTALS"]
        f5 = rows["F5_TEAM_TOTALS"]

        self.assertTrue(team["provider_expected"])
        self.assertEqual(team["acquisition_route"], "team_total_odds_source:team_totals")
        self.assertEqual(team["terminal_if_absent"], "ACQUISITION_MISSING")

        self.assertFalse(f5["provider_expected"])
        self.assertEqual(f5["acquisition_route"], "UNMAPPED_PROVIDER_MARKET")
        self.assertEqual(f5["terminal_if_absent"], "PROVIDER_UNSUPPORTED")

        audit = json.loads(Path("config/mlb_provider_capability_audit.json").read_text(encoding="utf-8"))
        self.assertIn("team_totals", audit["published_baseball_period_market_keys_relevant_to_catalog"])
        self.assertNotIn("TEAM_TOTALS", audit["external_markets"])
        self.assertEqual(
            audit["external_markets"]["F5_TEAM_TOTALS"]["checked_equivalent"],
            "team_totals_1st_5_innings",
        )
        self.assertEqual(audit["external_markets"]["F5_TEAM_TOTALS"]["status"], "NO_PUBLISHED_EQUIVALENT")

    def test_source_capability_is_not_runtime_or_evidence_promotion(self):
        # Source capability means only that a canonical price can be acquired or
        # normalized. It does not imply sportsbook availability, model promotion,
        # or validation evidence.
        self.assertEqual(len(COUNT_MARKETS), 26)
        self.assertEqual(len(ADDITIONAL_MARKETS), 7)
        self.assertEqual(len(FEATURED_GAME_MARKETS), 3)
        self.assertEqual(len(TEAM_TOTAL_MARKETS), 1)
        self.assertEqual(UNMAPPED_NORMALIZED_MARKETS, {"F5_TEAM_TOTALS"})


if __name__ == "__main__":
    unittest.main()
