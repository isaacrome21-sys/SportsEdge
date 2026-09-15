import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.edge_floors import load_edge_floor_config, require_frozen_devig_policy, require_production_edge_floor
from sportsedge.football_prop_surface import FootballPropSurfaceError, require_executable_prop_surface
from sportsedge.market_ids import (
    MarketIdError,
    canonical_evidence_market_id,
    canonical_market_id,
    load_market_id_config,
)

ROOT = Path(__file__).resolve().parents[1]
SURFACE = ROOT / "config/football_prop_engine_surface.json"
FLOORS = ROOT / "config/truth_gate_floors.json"
BUILD_ORDER = ROOT / "config/research/mlb_cfb_prop_engine_build_order_v1.json"
MARKET_IDS = ROOT / "config/market_id_canonicalization_v1.json"
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

    def test_schema_v3_floor_consumers_work_without_granting_prop_authority(self):
        config = load_edge_floor_config(str(FLOORS))
        require_frozen_devig_policy(config=config)
        floor = require_production_edge_floor(
            sport="nfl", market="passing_yards", path=str(FLOORS)
        )
        self.assertEqual(floor.schema_version, 3)
        self.assertEqual(floor.sport, "nfl")
        self.assertEqual(str(floor.value_probability_points), "0.03")
        self.assertEqual(floor.provenance_status, "FROZEN_BEFORE_JUDGED_STREAM")
        self.assertEqual(floor.evidence_sha256, "")
        self.assertEqual(floor.frozen_by_commit, "")

    def test_mlb_market_id_collisions_resolve_to_one_canonical_id(self):
        pairs = {
            ("strikeouts_batter", "strikeouts_hitter"): "hitter_strikeouts",
            ("pitcher_strikeouts", "strikeouts_pitcher"): "pitcher_strikeouts",
            ("rbis", "rbi"): "hitter_rbi",
            ("batters_faced", "pitcher_batters_faced"): "pitcher_batters_faced",
        }
        for aliases, canonical in pairs.items():
            with self.subTest(canonical=canonical):
                self.assertEqual(
                    {canonical_market_id("mlb", alias) for alias in aliases},
                    {canonical},
                )

    def test_evidence_identity_is_sport_scoped(self):
        self.assertEqual(canonical_evidence_market_id("mlb", "game_total"), "mlb:total")
        self.assertEqual(canonical_evidence_market_id("nfl", "game_total"), "nfl:total")
        self.assertEqual(canonical_evidence_market_id("cfb", "game_total"), "cfb:total")
        self.assertEqual(
            len({canonical_evidence_market_id(sport, "game_total") for sport in ("mlb", "nfl", "cfb")}),
            3,
        )

    def test_unknown_market_id_fails_closed(self):
        with self.assertRaisesRegex(MarketIdError, "UNKNOWN_MARKET_ID"):
            canonical_market_id("nfl", "unmapped_future_market")
        with self.assertRaisesRegex(MarketIdError, "UNKNOWN_MARKET_ID"):
            canonical_evidence_market_id("mlb", "unmapped_future_market")

    def test_registry_canonical_set_is_closed(self):
        config = load_market_id_config(str(MARKET_IDS))
        for sport, registry in config["sports"].items():
            for canonical in registry:
                with self.subTest(sport=sport, canonical=canonical):
                    self.assertEqual(canonical_market_id(sport, canonical, config=config), canonical)
                    self.assertEqual(
                        canonical_evidence_market_id(sport, canonical, config=config),
                        f"{sport}:{canonical}",
                    )

    def test_every_frozen_floor_market_resolves_exactly_once(self):
        floors = json.loads(FLOORS.read_text(encoding="utf-8"))["truth_gate"]["edge_floors"]
        for sport, markets in floors.items():
            for market in markets:
                with self.subTest(sport=sport, market=market):
                    canonical = canonical_market_id(sport, market)
                    self.assertEqual(
                        canonical_evidence_market_id(sport, market),
                        f"{sport.lower()}:{canonical}",
                    )

    def test_every_frozen_prop_market_surface_resolves_exactly_once(self):
        policy = json.loads(BUILD_ORDER.read_text(encoding="utf-8"))
        for sport in ("MLB", "CFB"):
            markets = list(policy[sport]["stage_3_joint_player_distributions"])
            markets.extend(policy[sport]["stage_7_market_binding"]["markets"])
            if sport == "MLB":
                markets.append("home_run")
            else:
                markets.append("anytime_td")
            for market in markets:
                with self.subTest(sport=sport, market=market):
                    canonical = canonical_market_id(sport, market)
                    self.assertEqual(
                        canonical_evidence_market_id(sport, market),
                        f"{sport.lower()}:{canonical}",
                    )

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
