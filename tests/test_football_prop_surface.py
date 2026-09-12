from __future__ import annotations

import json
from pathlib import Path
import unittest

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.football_prop_surface import FootballPropSurfaceError, require_executable_prop_surface

CFB_ARTIFACT_SHA = "923cfd1be42d31a87d9f31ddffce406d44bfc1bb003d1c625f5a4258f7773f23"


class FootballPropSurfaceTests(unittest.TestCase):
    def test_nfl_is_no_engine_while_cfb_remains_runtime_bound(self):
        with self.assertRaisesRegex(FootballPropSurfaceError, "FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:NFL"):
            require_executable_prop_surface("NFL")

        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        nfl = payload["sports"]["NFL"]
        self.assertEqual(nfl["engine_state"], "NO_ENGINE")
        self.assertEqual(nfl["promotion_state"], "BLOCKED_PENDING_INDEPENDENT_PROBABILITY_ENGINE_VALIDATION")
        self.assertEqual(nfl["readiness_state"], "NO_ENGINE")
        self.assertIn("nfl_player_props", payload["explicit_no_engine"])

        cfb = require_executable_prop_surface("CFB")
        self.assertEqual(cfb["engine_state"], "IMPLEMENTED_FAIL_CLOSED")
        self.assertEqual(cfb["promotion_state"], "AUTOMATIC_TRUTH_GATE_GATED")
        self.assertEqual(cfb["readiness_state"], "REGISTRY_DERIVED")
        self.assertEqual(cfb["runtime_state"], "ARTIFACT_FROZEN_EVIDENCE_GATED")
        self.assertEqual(cfb["frozen_artifact_sha256"], CFB_ARTIFACT_SHA)
        self.assertTrue(cfb["certification_registry"].endswith("_prop_certification.json"))

    def test_declared_provider_surface_matches_extended_run_machine_exactly(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        declared = {market for values in payload["implemented_provider_markets"].values() for market in values}
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

    def test_governance_has_no_market_price_model_p_shortcut(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        governance = payload["governance"]
        self.assertFalse(governance["market_prices_can_create_model_p"])
        self.assertFalse(governance["hit_rates_can_create_model_p"])
        self.assertFalse(governance["capper_or_consensus_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_fair_market_p"])
        self.assertTrue(governance["requires_artifact_bound_certification"])
        self.assertTrue(governance["requires_frozen_edge_floor_before_promotable_inference"])

    def test_checked_in_freeze_registries_remain_truthful_research_records(self):
        nfl = json.loads(Path("config/nfl_prop_model_freeze.json").read_text())
        self.assertEqual(nfl["status"], "FROZEN")
        self.assertEqual(
            nfl["artifact_sha256"],
            "3efa5cc92b5ed1bf53a99cbe0d6e7792d01791a77c8f684874d66213b73d9570",
        )
        self.assertTrue(Path(nfl["artifact_path"]).is_file())
        self.assertFalse(nfl["promotion_authority"])

        cfb = json.loads(Path("config/cfb_prop_model_freeze.json").read_text())
        self.assertEqual(cfb["status"], "FROZEN")
        self.assertEqual(cfb["artifact_sha256"], CFB_ARTIFACT_SHA)
        self.assertTrue(Path(cfb["artifact_path"]).is_file())
        self.assertFalse(cfb["promotion_authority"])


if __name__ == "__main__":
    unittest.main()
