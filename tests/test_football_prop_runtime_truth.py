import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.football_prop_surface import FootballPropSurfaceError, require_executable_prop_surface

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "config/football_prop_engine_surface.json"


class FootballPropRuntimeTruthTests(unittest.TestCase):
    def test_checked_in_nfl_and_cfb_are_artifact_blocked_when_unfrozen(self):
        for sport in ("NFL", "CFB"):
            with self.subTest(sport=sport):
                spec = require_executable_prop_surface(sport, path=SURFACE)
                self.assertEqual(spec["runtime_state"], "MODEL_ARTIFACT_BLOCKED")
                self.assertIsNone(spec["frozen_artifact_sha256"])
                self.assertEqual(spec["readiness_state"], "REGISTRY_DERIVED")

    def test_surface_does_not_claim_market_price_can_create_model_p(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        governance = payload["governance"]
        self.assertFalse(governance["market_prices_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_fair_market_p"])
        self.assertTrue(governance["one_sided_offer_ev_allowed_with_model_p"])
        self.assertTrue(governance["paired_price_required_for_devig"])
        self.assertNotIn("requires_paired_price_for_market_economics", governance)

    def test_frozen_registry_requires_real_sha(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"; config.mkdir()
            (config / "football_prop_engine_surface.json").write_text(json.dumps(payload), encoding="utf-8")
            for sport in ("nfl", "cfb"):
                (config / f"{sport}_prop_model_freeze.json").write_text(json.dumps({"sport": sport.upper(), "status": "FROZEN", "artifact_sha256": None}), encoding="utf-8")
            with self.assertRaisesRegex(FootballPropSurfaceError, "FOOTBALL_PROP_FROZEN_ARTIFACT_SHA_INVALID:NFL"):
                require_executable_prop_surface("NFL", path=config / "football_prop_engine_surface.json")

    def test_registry_state_is_derived_not_hard_coded(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"; config.mkdir()
            surface_path = config / "football_prop_engine_surface.json"
            surface_path.write_text(json.dumps(payload), encoding="utf-8")
            digest = "a" * 64
            (config / "nfl_prop_model_freeze.json").write_text(json.dumps({"sport": "NFL", "status": "FROZEN", "artifact_sha256": digest}), encoding="utf-8")
            spec = require_executable_prop_surface("NFL", path=surface_path)
            self.assertEqual(spec["runtime_state"], "ARTIFACT_FROZEN_EVIDENCE_GATED")
            self.assertEqual(spec["frozen_artifact_sha256"], digest)


if __name__ == "__main__":
    unittest.main()
