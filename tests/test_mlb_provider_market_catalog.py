import json
from pathlib import Path
import unittest

from sportsedge.sports.mlb.provider_market_catalog import (
    NO_DIRECT_PROVIDER_KEY,
    PROVIDER_KEY_BY_MARKET,
    provider_key_for_market,
    validate_provider_coverage,
)

ROOT = Path(__file__).resolve().parents[1]


class MLBProviderMarketCatalogTests(unittest.TestCase):
    def test_all_38_have_exactly_one_provider_disposition(self):
        catalog = json.loads((ROOT / "config" / "mlb_market_catalog.json").read_text(encoding="utf-8"))
        report = validate_provider_coverage(catalog)
        self.assertEqual(report["status"], "COMPLETE")
        self.assertEqual(report["canonical_market_count"], 38)
        self.assertEqual(report["direct_market_count"], 26)
        self.assertEqual(report["no_direct_market_count"], 12)
        self.assertEqual(report["missing_disposition"], [])
        self.assertEqual(report["extra_disposition"], [])
        self.assertEqual(report["overlap"], [])

    def test_no_direct_markets_are_not_synthesized(self):
        for market in ("NRFI", "YRFI", "EXTRA_BASE_HITS", "PITCHER_HITS_WALKS_ER", "F5_TEAM_TOTALS"):
            self.assertIn(market, NO_DIRECT_PROVIDER_KEY)
            self.assertIsNone(provider_key_for_market(market))

    def test_documented_direct_examples_map(self):
        self.assertEqual(PROVIDER_KEY_BY_MARKET["MONEYLINE"], "h2h")
        self.assertEqual(PROVIDER_KEY_BY_MARKET["HITS"], "batter_hits")
        self.assertEqual(PROVIDER_KEY_BY_MARKET["PITCHER_K"], "pitcher_strikeouts")
        self.assertEqual(PROVIDER_KEY_BY_MARKET["F5_RUN_LINE"], "spreads_1st_5_innings")


if __name__ == "__main__":
    unittest.main()
