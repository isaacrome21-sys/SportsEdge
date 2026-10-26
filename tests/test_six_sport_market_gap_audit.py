"""Synthetic catalog fixture: coverage auditing, not price/model validation."""
import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.research.six_sport_market_gap_audit import audit_market_gaps


class MarketGapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.write("config/run_it_surface.json", {"sports": {"NFL": {"automatic_command": ["run"]}, "CFB": {"automatic_command": ["run"]}, "MLB": {"automatic_command": ["run"]}, "NBA": {"automatic_command": None, "blocker": "NBA_NOT_WIRED"}}})
        self.write("config/football_market_surface.json", {"markets": [
            {"family": "game", "market": "moneyline", "engine_state_by_sport": {"NFL": "IMPLEMENTED", "CFB": "IMPLEMENTED"}},
            {"family": "game", "market": "team_total", "engine_state_by_sport": {"NFL": "NO_ENGINE", "CFB": "IMPLEMENTED"}},
            {"family": "qb", "market": "passing_yards", "engine_state_by_sport": {"NFL": "IMPLEMENTED", "CFB": "IMPLEMENTED"}}]})
        self.write("config/football_prop_engine_surface.json", {"sports": {"NFL": {"engine_state": "NO_ENGINE"}, "CFB": {"engine_state": "NO_ENGINE"}}})
        self.write("config/mlb_market_catalog.json", {key: ["MONEYLINE"] if key == "game_markets" else [] for key in (
            "game_markets", "batter_markets", "pitcher_markets", "separate_protocol_markets", "binary_markets_not_coerced", "period_markets_not_coerced")})
        self.write_text("sportsedge/sports/nhl/market_capabilities.py", '_CAPABILITIES = {"TOTAL": object(), "PUCK_LINE": object()}\n')

    def write(self, path, obj):
        self.write_text(path, json.dumps(obj))

    def write_text(self, path, text):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def row(self, sport, market):
        return next(r for r in audit_market_gaps(self.root)["market_rows"] if r["sport"] == sport and r["market"] == market)

    def test_all_six_sports(self): self.assertEqual(len(audit_market_gaps(self.root)["sports"]), 6)
    def test_missing_nhl_lane_visible(self): self.assertEqual(self.row("NHL", "__AUTOMATIC_LANE__")["status"], "MISSING_LANE")
    def test_missing_cbb_lane_visible(self): self.assertEqual(self.row("CBB", "__AUTOMATIC_LANE__")["status"], "MISSING_LANE")
    def test_nba_lane_visible(self): self.assertEqual(self.row("NBA", "__AUTOMATIC_LANE__")["status"], "NO_AUTOMATIC_CAPTURE")
    def test_football_game_not_promoted(self): self.assertEqual(self.row("NFL", "MONEYLINE")["status"], "UNVERIFIED_ENGINE_PATH")
    def test_cfb_game_research_only(self): self.assertEqual(self.row("CFB", "MONEYLINE")["status"], "RESEARCH_ONLY")
    def test_cfb_team_total_blocked(self): self.assertEqual(self.row("CFB", "TEAM_TOTAL")["status"], "BLOCKED")
    def test_nfl_prop_no_engine(self): self.assertEqual(self.row("NFL", "PASSING_YARDS")["status"], "NO_ENGINE")
    def test_cfb_prop_no_engine(self): self.assertEqual(self.row("CFB", "PASSING_YARDS")["status"], "NO_ENGINE")
    def test_mlb_catalog_only(self): self.assertEqual(self.row("MLB", "MONEYLINE")["status"], "CATALOG_ONLY_UNVERIFIED")
    def test_nba_prop_research_only(self): self.assertEqual(self.row("NBA", "PLAYER_POINTS")["status"], "RESEARCH_ONLY")
    def test_nba_game_blocked(self): self.assertEqual(self.row("NBA", "TOTAL")["status"], "BLOCKED")
    def test_nhl_requires_engine(self): self.assertEqual(self.row("NHL", "PUCK_LINE")["status"], "REQUIRES_ENGINE")
    def test_cbb_unenumerated(self): self.assertEqual(self.row("CBB", "__UNENUMERATED_MARKETS__")["status"], "BLOCKED")
    def test_never_claim_complete(self): self.assertFalse(audit_market_gaps(self.root)["complete_market_coverage"])
    def test_never_claim_price(self): self.assertTrue(all(not r["priced"] for r in audit_market_gaps(self.root)["market_rows"]))
    def test_never_claim_production(self): self.assertTrue(all(not r["production_eligible"] for r in audit_market_gaps(self.root)["market_rows"]))
    def test_missing_football_catalog_refused(self):
        (self.root / "config/football_market_surface.json").unlink()
        with self.assertRaisesRegex(ValueError, "SOURCE_MISSING_OR_INVALID"):
            audit_market_gaps(self.root)
    def test_missing_nhl_catalog_refused(self):
        (self.root / "sportsedge/sports/nhl/market_capabilities.py").unlink()
        with self.assertRaisesRegex(ValueError, "NHL_CATALOG_UNREADABLE"):
            audit_market_gaps(self.root)
    def test_missing_mlb_category_refused(self):
        self.write("config/mlb_market_catalog.json", {"game_markets": []})
        with self.assertRaisesRegex(ValueError, "MLB_CATALOG_CATEGORY_MISSING"):
            audit_market_gaps(self.root)


if __name__ == "__main__": unittest.main()
