import json
from pathlib import Path
import tempfile
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
            with self.assertRaisesRegex(
                FootballPropSurfaceError,
                f"FOOTBALL_PROP_ENGINE_NOT_IMPLEMENTED:{sport}",
            ):
                require_executable_prop_surface(sport, path=SURFACE)

        nfl_registry = json.loads((ROOT / "config/nfl_prop_model_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(nfl_registry["status"], "FROZEN")
        self.assertEqual(nfl_registry["artifact_sha256"], NFL_CERTIFIED_SHA)
        self.assertFalse(nfl_registry["promotion_authority"])

        cfb_registry = json.loads((ROOT / "config/cfb_prop_model_freeze.json").read_text(encoding="utf-8"))
        self.assertEqual(cfb_registry["status"], "FROZEN")
        self.assertEqual(cfb_registry["artifact_sha256"], CFB_CERTIFIED_SHA)
        self.assertFalse(cfb_registry["promotion_authority"])

        participation = json.loads((ROOT / "config/cfb_prop_participation_model_v1.json").read_text(encoding="utf-8"))
        self.assertEqual(participation["status"], "UNFITTED_RESEARCH_ONLY")
        self.assertEqual(participation["engine_validation_status"], "NOT_RUN")
        self.assertFalse(participation["promotion_authority"])
        self.assertFalse(participation["activation_authority"])

    def test_surface_does_not_claim_market_price_can_create_model_p(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        governance = payload["governance"]
        self.assertFalse(governance["market_prices_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_model_p"])
        self.assertFalse(governance["one_sided_market_can_create_fair_market_p"])
        self.assertTrue(governance["one_sided_offer_ev_allowed_with_model_p"])
        self.assertTrue(governance["paired_price_required_for_devig"])
        self.assertTrue(governance["cfb_requires_frozen_participation_model_before_engine_activation"])
        self.assertNotIn("requires_paired_price_for_market_economics", governance)

    def test_executable_frozen_registry_requires_real_sha(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        payload["sports"]["CFB"]["engine_state"] = "IMPLEMENTED_FAIL_CLOSED"
        payload["sports"]["CFB"]["readiness_state"] = "REGISTRY_DERIVED"
        payload["sports"]["CFB"]["promotion_state"] = "AUTOMATIC_TRUTH_GATE_GATED"
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"; config.mkdir()
            (config / "football_prop_engine_surface.json").write_text(json.dumps(payload), encoding="utf-8")
            (config / "cfb_prop_model_freeze.json").write_text(json.dumps({"sport": "CFB", "status": "FROZEN", "artifact_sha256": None}), encoding="utf-8")
            with self.assertRaisesRegex(FootballPropSurfaceError, "FOOTBALL_PROP_FROZEN_ARTIFACT_SHA_INVALID:CFB"):
                require_executable_prop_surface("CFB", path=config / "football_prop_engine_surface.json")

    def test_cfb_activation_requires_frozen_forward_validated_participation_model(self):
        payload = json.loads(SURFACE.read_text(encoding="utf-8"))
        payload["sports"]["CFB"]["engine_state"] = "IMPLEMENTED_FAIL_CLOSED"
        payload["sports"]["CFB"]["readiness_state"] = "REGISTRY_DERIVED"
        payload["sports"]["CFB"]["promotion_state"] = "AUTOMATIC_TRUTH_GATE_GATED"
        with tempfile.TemporaryDirectory() as td:
            config = Path(td) / "config"; config.mkdir()
            surface_path = config / "football_prop_engine_surface.json"
            surface_path.write_text(json.dumps(payload), encoding="utf-8")
            digest = "a" * 64
            (config / "cfb_prop_model_freeze.json").write_text(json.dumps({"sport": "CFB", "status": "FROZEN", "artifact_sha256": digest}), encoding="utf-8")

            unfitted = json.loads((ROOT / "config/cfb_prop_participation_model_v1.json").read_text(encoding="utf-8"))
            participation_path = config / "cfb_prop_participation_model_v1.json"
            participation_path.write_text(json.dumps(unfitted), encoding="utf-8")
            with self.assertRaisesRegex(FootballPropSurfaceError, "CFB_PROP_PARTICIPATION_MODEL_NOT_FROZEN"):
                require_executable_prop_surface("CFB", path=surface_path)

            fitted = dict(unfitted)
            fitted.update({
                "status": "FROZEN",
                "engine_validation_status": "PASSED",
                "artifact_path": "artifacts/football/cfb_participation_model_v1.json",
                "artifact_sha256": "b" * 64,
                "fit_code_git_sha": "c" * 40,
                "training_source_manifest_sha256": "d" * 64,
            })
            participation_path.write_text(json.dumps(fitted), encoding="utf-8")
            spec = require_executable_prop_surface("CFB", path=surface_path)
            self.assertEqual(spec["runtime_state"], "ARTIFACT_FROZEN_EVIDENCE_GATED")
            self.assertEqual(spec["frozen_artifact_sha256"], digest)
            self.assertEqual(spec["participation_model_artifact_sha256"], "b" * 64)
            self.assertEqual(spec["participation_model_validation_status"], "PASSED")


if __name__ == "__main__":
    unittest.main()
