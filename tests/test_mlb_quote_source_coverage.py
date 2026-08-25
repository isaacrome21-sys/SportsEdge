import json
import unittest
from pathlib import Path

from sportsedge.additional_mlb_odds_source import CANONICAL_MARKETS as ADDITIONAL_MARKETS
from sportsedge.draftkings_prop_source import COUNT_MARKETS
from sportsedge.quote_bridge import SUPPORTED_MARKETS
from sportsedge.team_total_odds_source import TEAM_TOTAL_PROVIDER_MARKET


FEATURED_GAME_MARKETS = frozenset({"MONEYLINE", "RUN_LINE", "TOTALS"})


class MLBQuoteSourceCoverageTests(unittest.TestCase):
    @staticmethod
    def _catalog_markets():
        raw = json.loads(Path("config/mlb_market_catalog.json").read_text())
        markets = set()
        for key, rows in raw.items():
            if key == "schema_version" or not isinstance(rows, list):
                continue
            for row in rows:
                if isinstance(row, str):
                    markets.add(row)
                elif isinstance(row, dict) and row.get("market"):
                    markets.add(str(row["market"]))
        return markets

    @staticmethod
    def _surface_rows():
        raw = json.loads(Path("config/mlb_market_surface.json").read_text())
        return {str(row["market"]): row for row in raw["markets"]}

    def test_declared_source_capability_covers_entire_canonical_surface(self):
        count = frozenset(COUNT_MARKETS)
        additional = frozenset(ADDITIONAL_MARKETS)
        self.assertFalse(count & FEATURED_GAME_MARKETS)
        self.assertFalse(count & additional)
        self.assertFalse(FEATURED_GAME_MARKETS & additional)
        self.assertEqual(TEAM_TOTAL_PROVIDER_MARKET, "team_totals")

        source_capability = count | FEATURED_GAME_MARKETS | additional | {"TEAM_TOTALS"}
        surface = self._surface_rows()
        explicitly_unsupported = {
            market
            for market, row in surface.items()
            if row.get("provider_expected") is False
        }
        canonical = self._catalog_markets()

        self.assertEqual(source_capability | explicitly_unsupported, canonical)
        self.assertFalse(source_capability & explicitly_unsupported)
        self.assertEqual(set(SUPPORTED_MARKETS), canonical)
        self.assertEqual(explicitly_unsupported, {"F5_TEAM_TOTALS"})
        self.assertEqual(surface["TEAM_TOTALS"]["acquisition_route"], "team_total_odds_source:alternate")
        self.assertEqual(surface["F5_TEAM_TOTALS"]["acquisition_route"], "UNMAPPED_PROVIDER_MARKET")

    def test_source_capability_is_not_runtime_or_evidence_promotion(self):
        # Quote-source support is distinct from sportsbook offering, runtime pricing,
        # or validation evidence. One canonical market is deliberately unsupported.
        self.assertEqual(len(COUNT_MARKETS), 26)
        self.assertEqual(len(ADDITIONAL_MARKETS), 7)
        self.assertEqual(len(FEATURED_GAME_MARKETS), 3)
        self.assertEqual(len(self._catalog_markets()), len(SUPPORTED_MARKETS))
        self.assertEqual(self._surface_rows()["F5_TEAM_TOTALS"]["terminal_if_absent"], "PROVIDER_UNSUPPORTED")


if __name__ == "__main__":
    unittest.main()
