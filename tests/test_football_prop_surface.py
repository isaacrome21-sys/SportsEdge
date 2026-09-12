from __future__ import annotations

import json
from pathlib import Path
import unittest

from sportsedge.football_prop_extended_run_machine import PROVIDER_MARKETS
from sportsedge.football_prop_surface import FootballPropSurfaceError, require_executable_prop_surface

CFB_ARTIFACT_SHA = "923cfd1be42d31a87d9f31ddffce406d44bfc1bb003d1c625f5a4258f7773f23"


class FootballPropSurfaceTests(unittest.TestCase):
    def _assert_no_engine(self, sport: str):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        self.assertEqual(payload["sports"][sport]["engine_state"], "NO_ENGINE")
        self.assertEqual(payload["sports"][sport]["readiness_state"], "NO_ENGINE")
        self.assertIn(sport, payload["explicit_no_engine"])
        with self.assertRaisesRegex(
            FootballPropSurfaceError,
            f"FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:{sport}",
        ):
            require_executable_prop_surface(sport)

    def test_nfl_is_explicit_no_engine_until_independently_validated(self):
        self._assert_no_engine("NFL")

    def test_cfb_is_explicit_no_engine_until_independently_validated(self):
        self._assert_no_engine("CFB")
        freeze = json.loads(Path("config/cfb_prop_model_freeze.json").read_text())
        self.assertEqual(freeze["status"], "FROZEN")
        self.assertEqual(freeze["artifact_sha256"], CFB_ARTIFACT_SHA)
        self.assertFalse(freeze["promotion_authority"])

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
        self.assertIn("NFL", payload["explicit_no_engine"])
        self.assertIn("CFB", payload["explicit_no_engine"])
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

    def test_one_sided_scorer_market_consumes_model_p_but_cannot_create_it(self):
        payload = json.loads(Path("config/football_prop_engine_surface.json").read_text())
        governance = payload["governance"]
        self.assertFalse(governance["one_sided_market_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_fair_market_p"])
        self.assertTrue(governance["one_sided_offer_ev_allowed_with_model_p"])
        self.assertTrue(governance["paired_price_required_for_devig"])
        self.assertNotIn("requires_paired_price_for_market_economics", governance)

    def test_checked_in_freeze_registries_remain_truthful_but_non_authoritative(self):
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
