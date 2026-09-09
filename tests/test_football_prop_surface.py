from __future__ import annotations

import json
from pathlib import Path
import unittest

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.football_prop_surface import require_executable_prop_surface


class FootballPropSurfaceTests(unittest.TestCase):
    def test_nfl_and_cfb_surface_is_runtime_bound_and_truth_gate_promotable(self):
        for sport in ("NFL", "CFB"):
            spec = require_executable_prop_surface(sport)
            self.assertEqual(spec["engine_state"], "IMPLEMENTED_FAIL_CLOSED")
            self.assertEqual(spec["promotion_state"], "AUTOMATIC_TRUTH_GATE_GATED")
            self.assertEqual(spec["current_state"], "EVIDENCE_PENDING")
            self.assertTrue(spec["certification_registry"].endswith("_prop_certification.json"))

    def test_declared_provider_surface_matches_extended_run_machine_exactly(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        declared = {
            market
            for values in payload["implemented_provider_markets"].values()
            for market in values
        }
        self.assertEqual(declared, set(PROVIDER_MARKETS))
        self.assertIn("player_anytime_td", declared)
        self.assertIn("player_tds_over", declared)
        self.assertIn("player_field_goals", declared)
        self.assertIn("player_kicking_points", declared)
        self.assertIn("player_sacks", declared)
        self.assertIn("player_tackles_assists", declared)
        self.assertIn("targets", payload["explicit_no_engine"])
        self.assertIn("first_td", payload["explicit_no_engine"])
        self.assertIn("last_td", payload["explicit_no_engine"])
        self.assertNotIn("anytime_td", payload["explicit_no_engine"])
        self.assertNotIn("kicker_props", payload["explicit_no_engine"])
        self.assertNotIn("defensive_player_props", payload["explicit_no_engine"])

    def test_governance_has_no_permanent_official_or_manual_toggle_veto(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        governance = payload["governance"]
        self.assertTrue(governance["official_bets_allowed_when_all_gates_pass"])
        self.assertFalse(governance["manual_eligible_toggle_required"])
        self.assertTrue(governance["requires_artifact_bound_certification"])
        self.assertTrue(governance["requires_frozen_edge_floor_before_promotable_inference"])

    def test_one_sided_scorer_market_cannot_create_fair_market_probability(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        governance = payload["governance"]
        self.assertTrue(governance["one_sided_market_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_fair_market_p"])
        self.assertTrue(governance["requires_paired_price_for_market_economics"])

    def test_checked_in_freeze_registries_remain_truthful(self):
        # Hosted exact-SHA freeze bundles are separate immutable CI artifacts;
        # checked-in registries must not claim a local artifact that is absent.
        for sport in ("nfl", "cfb"):
            row = json.loads(Path(f"config/{sport}_prop_model_freeze.json").read_text())
            self.assertEqual(row["status"], "UNFROZEN")
            self.assertIsNone(row["artifact_sha256"])
            self.assertFalse((Path(row["artifact_path"])).is_file())


if __name__ == "__main__":
    unittest.main()
