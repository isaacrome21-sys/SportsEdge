import json
from pathlib import Path
import unittest

from sportsedge.football_prop_surface import FootballPropSurfaceError, require_executable_prop_surface

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "config/football_prop_engine_surface.json"
NFL_CERTIFIED_SHA = "3efa5cc92b5ed1bf53a99cbe0d6e7792d01791a77c8f684874d66213b73d9570"
CFB_CERTIFIED_SHA = "923cfd1be42d31a87d9f31ddffce406d44bfc1bb003d1c625f5a4258f7773f23"


class FootballPropRuntimeTruthTests(unittest.TestCase):
    def test_checked_in_football_prop_artifacts_remain_truthful_without_granting_engine_authority(self):
        surface = json.loads(SURFACE.read_text(encoding="utf-8"))
        for sport in ("NFL", "CFB"):
            self.assertEqual(surface["sports"][sport]["engine_state"], "NO_ENGINE")
            with self.assertRaisesRegex(FootballPropSurfaceError, f"FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:{sport}"):
                require_executable_prop_surface(sport, path=SURFACE)

        nfl_registry = json.loads((ROOT / "config/nfl_prop_model_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(nfl_registry["status"], "FROZEN")
        self.assertEqual(nfl_registry["artifact_sha256"], NFL_CERTIFIED_SHA)
        self.assertFalse(nfl_registry["promotion_authority"])

        cfb_registry = json.loads((ROOT / "config/cfb_prop_model_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(cfb_registry["status"], "FROZEN")
        self.assertEqual(cfb_registry["artifact_sha256"], CFB_CERTIFIED_SHA)
        self.assertFalse(cfb_registry["promotion_authority"])

    def test_surface_does_not_claim_market_price_can_create_model_p(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        governance = payload["governance"]
        self.assertFalse(governance["market_prices_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_fair_market_p"])
        self.assertTrue(governance["one_sided_offer_ev_allowed_with_model_p"])
        self.assertTrue(governance["paired_price_required_for_devig"])
        self.assertNotIn("requires_paired_price_for_market_economics", governance)

    def test_no_engine_state_short_circuits_registry_authority(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        self.assertEqual(payload["sports"]["CFB"]["engine_state"], "NO_ENGINE")
        with self.assertRaisesRegex(FootballPropSurfaceError, "FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:CFB"):
            require_executable_prop_surface("CFB", path=SURFACE)


if __name__ == "__main__":
    unittest.main()
