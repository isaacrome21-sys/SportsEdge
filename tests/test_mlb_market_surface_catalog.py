import json
import unittest
from pathlib import Path

from sportsedge.market_surface import load_market_surface


CATALOG = Path("config/mlb_market_catalog.json")
SURFACE = Path("config/mlb_market_surface.json")


def _catalog_markets():
    raw = json.loads(CATALOG.read_text())
    out = set()
    for key, value in raw.items():
        if key == "schema_version":
            continue
        if isinstance(value, list):
            out.update(str(x) for x in value)
    return out


class MLBMarketSurfaceCatalogTests(unittest.TestCase):
    def test_surface_is_exactly_catalog_complete(self):
        version, specs = load_market_surface(SURFACE)
        self.assertEqual(version, "mlb_market_surface_v2")
        self.assertEqual(len(specs), 38)
        self.assertEqual({spec.market for spec in specs}, _catalog_markets())

    def test_current_unmapped_provider_set_is_explicit_and_fail_closed(self):
        raw = json.loads(SURFACE.read_text())
        unsupported = {
            row["market"]
            for row in raw["markets"]
            if row["provider_expected"] is False
        }
        self.assertEqual(
            unsupported,
            {
                "F5_TEAM_TOTALS",
                "EXTRA_BASE_HITS",
                "HITS_RUNS_STOLEN_BASES",
                "RUNS_RBIS",
                "HITS_STOLEN_BASES",
                "HITS_WALKS_STOLEN_BASES",
                "PITCHER_HITS_WALKS_ER",
                "EITHER_PITCHER_HITS_ALLOWED",
                "EITHER_PITCHER_BB",
                "EITHER_PITCHER_ER",
            },
        )
        for row in raw["markets"]:
            self.assertTrue(str(row.get("acquisition_route") or "").strip())
            if row["market"] in unsupported:
                self.assertEqual(row["terminal_if_absent"], "PROVIDER_UNSUPPORTED")
                self.assertFalse(row["retry_eligible"])
                self.assertEqual(row["acquisition_route"], "UNMAPPED_PROVIDER_MARKET")

    def test_every_provider_expected_market_has_named_acquisition_route(self):
        raw = json.loads(SURFACE.read_text())
        for row in raw["markets"]:
            if row["provider_expected"]:
                self.assertNotEqual(row["acquisition_route"], "UNMAPPED_PROVIDER_MARKET")
                self.assertIn(":", row["acquisition_route"])


if __name__ == "__main__":
    unittest.main()
