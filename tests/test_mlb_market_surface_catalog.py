import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.market_surface import MarketSurfaceError, load_market_surface


CATALOG = Path("config/mlb_market_catalog.json")
SURFACE = Path("config/mlb_market_surface.json")


def _catalog_markets():
    raw = json.loads(CATALOG.read_text())
    out = set()
    for key, value in raw.items():
        if key == "schema_version":
            continue
        if isinstance(value, list):
            for row in value:
                if isinstance(row, str):
                    out.add(row)
                elif isinstance(row, dict) and row.get("market"):
                    out.add(str(row["market"]))
    return out


class MLBMarketSurfaceCatalogTests(unittest.TestCase):
    def test_surface_is_exactly_catalog_complete(self):
        version, specs = load_market_surface(SURFACE)
        self.assertEqual(version, "mlb_market_surface_v2")
        self.assertEqual({spec.market for spec in specs}, _catalog_markets())
        self.assertEqual(len(specs), len(_catalog_markets()))

    def test_surface_loader_fails_closed_when_metadata_drops_catalog_market(self):
        raw = json.loads(SURFACE.read_text())
        raw["markets"] = [row for row in raw["markets"] if row["market"] != "TEAM_TOTALS"]
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "surface.json"
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(MarketSurfaceError, "MARKET_SURFACE_CATALOG_MISMATCH"):
                load_market_surface(path)

    def test_surface_loader_fails_closed_when_metadata_invents_market(self):
        raw = json.loads(SURFACE.read_text())
        extra = dict(raw["markets"][0])
        extra["market"] = "INVENTED_MARKET"
        raw["markets"].append(extra)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "surface.json"
            path.write_text(json.dumps(raw))
            with self.assertRaisesRegex(MarketSurfaceError, "MARKET_SURFACE_CATALOG_MISMATCH"):
                load_market_surface(path)

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
