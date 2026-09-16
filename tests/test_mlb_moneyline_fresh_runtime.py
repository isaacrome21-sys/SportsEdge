from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import unittest
from unittest.mock import patch

from sportsedge.mlb_moneyline_forward_prediction import (
    PREDICTION_VERSION,
    PRODUCTION_ENGINE_DISPATCH,
)
from sportsedge.mlb_moneyline_fresh_runtime import (
    MLBMoneylineFreshRuntimeError,
    PASS_STATUS,
    evaluate_fresh_runtime_hard_checks,
)


ARTIFACT = "a" * 64
MODEL_INPUT_HASH = "b" * 64
DISTRIBUTION_SHA = "c" * 64
READOUT_SHA = "d" * 64
RAW_SHA = "e" * 64
FEATURE_HASH = "f" * 64


def _canonical_sha(value):
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _engine(model_input):
    side = str(model_input["side"])
    p = 0.60 if side == "HOME" else 0.40
    return {
        "game_id": model_input["game_id"],
        "market": model_input["market"],
        "entity_id": model_input["entity_id"],
        "line": model_input["line"],
        "side": side,
        "model_p": p,
        "push_p": 0.0,
        "runtime_path": "CANONICAL_V7",
        "model_input_hash": MODEL_INPUT_HASH if side == "HOME" else "1" * 64,
        "distribution_sha256": DISTRIBUTION_SHA,
        "readout_sha256": READOUT_SHA if side == "HOME" else "2" * 64,
        "readout_version": "test_readout_v1",
        "engine_version": "test_engine_v1",
        "seed_policy": "test_seed_v1",
        "mc_paths": int(model_input["simulations"]),
    }


class FreshRuntimeHardChecksTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
        self.start = self.now + timedelta(minutes=30)
        self.deployments = {
            "schema_version": 1,
            "markets": {
                "MONEYLINE": {
                    "eligible": False,
                    "stage": "VALIDATED_MATH",
                    "reason": "live production inference path not attested",
                }
            },
        }
        deployment_sha = _canonical_sha(self.deployments["markets"]["MONEYLINE"])
        self.readiness = {
            "schema_version": "mlb_moneyline_transition_readiness_v1",
            "status": "GOVERNANCE_DOCUMENTATION_COMPLETE_FRESH_RUNTIME_STILL_REQUIRED",
            "lane_id": "MLB_MONEYLINE_DK_T30_V1",
            "model_artifact_sha256": ARTIFACT,
            "market_definition_sha256": "3" * 64,
            "policy_id": "PROMOTION_EVIDENCE_POLICY_V2",
            "policy_sha256": "4" * 64,
            "transition_packet_sha256": "5" * 64,
            "deployment_snapshot_sha256": deployment_sha,
            "warning_clearance_status": "OFFICIAL_WARNING_CLEARANCE_PASS",
            "warning_clearance_sha256": "6" * 64,
            "governance_documentation_complete": True,
            "fresh_runtime_hard_checks_required": True,
            "state_transition_apply_now": False,
            "promotion_authority": False,
            "deployment_change_allowed": False,
            "staking_change_allowed": False,
            "official_change_allowed": False,
        }
        self.prediction = {
            "schema_version": PREDICTION_VERSION,
            "promotion_authority": False,
            "market": "MONEYLINE",
            "game_pk": 123,
            "away_team_id": 10,
            "away_team": "Away Club",
            "home_team_id": 20,
            "home_team": "Home Club",
            "model_side": "HOME",
            "market_blind": True,
            "event_start_ts": self.start.isoformat(),
            "feature_asof_ts": (self.now - timedelta(minutes=10)).isoformat(),
            "prediction_generated_at_utc": (self.now - timedelta(minutes=5)).isoformat(),
            "model_artifact_sha256": ARTIFACT,
            "feature_source_hash": FEATURE_HASH,
            "away_mean_runs": 4.1,
            "home_mean_runs": 4.8,
            "model_p": 0.60,
            "model_input_hash": MODEL_INPUT_HASH,
            "distribution_sha256": DISTRIBUTION_SHA,
            "readout_sha256": READOUT_SHA,
            "readout_version": "test_readout_v1",
            "engine_version": "test_engine_v1",
            "seed_policy": "test_seed_v1",
            "mc_paths": 100000,
            "production_engine_dispatch": PRODUCTION_ENGINE_DISPATCH,
        }
        self.capture = {
            "promotion_authority": False,
            "source_class": "DRAFTKINGS_DIRECT_WEB_V1",
            "sportsbook": "draftkings",
            "provider": "DRAFTKINGS_DIRECT_WEB",
            "sport_key": "baseball_mlb",
            "provider_event_id": "dk-123",
            "home_team": "Home Club",
            "away_team": "Away Club",
            "scheduled_start_utc": self.start.isoformat(),
            "observed_at_utc": (self.now - timedelta(seconds=10)).isoformat(),
            "model_artifact_sha256": ARTIFACT,
            "raw_sha256": RAW_SHA,
            "moneyline": {
                "status": "OK",
                "home_price_american": -120,
                "away_price_american": 110,
            },
        }

    def _evaluate(self, **overrides):
        args = {
            "transition_readiness": self.readiness,
            "prediction": self.prediction,
            "capture": self.capture,
            "deployments": self.deployments,
            "now": self.now,
        }
        args.update(overrides)
        with patch(
            "sportsedge.mlb_moneyline_fresh_runtime.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ), patch(
            "sportsedge.mlb_moneyline_fresh_runtime.engine_registry",
            return_value={"MONEYLINE": _engine},
        ):
            return evaluate_fresh_runtime_hard_checks(**args)

    def test_pass_is_non_authoritative_and_exercises_both_sides(self):
        report = self._evaluate()
        self.assertEqual(report["status"], PASS_STATUS)
        self.assertEqual(report["runtime_home_model_p"], 0.60)
        self.assertEqual(report["runtime_away_model_p"], 0.40)
        self.assertLess(report["quote_age_seconds"], report["max_quote_age_seconds"])
        self.assertFalse(report["deployment_eligible_during_check"])
        self.assertFalse(report["promotion_authority"])
        self.assertFalse(report["deployment_change_allowed"])
        self.assertFalse(report["staking_change_allowed"])
        self.assertFalse(report["official_change_allowed"])
        self.assertTrue(all(report["runtime_checks"].values()))

    def test_stale_quote_fails_closed(self):
        capture = dict(self.capture)
        capture["observed_at_utc"] = (self.now - timedelta(seconds=61)).isoformat()
        with self.assertRaisesRegex(MLBMoneylineFreshRuntimeError, "stale"):
            self._evaluate(capture=capture)

    def test_eligible_deployment_cannot_generate_pretransition_receipt(self):
        deployments = json.loads(json.dumps(self.deployments))
        deployments["markets"]["MONEYLINE"]["eligible"] = True
        with self.assertRaisesRegex(MLBMoneylineFreshRuntimeError, "eligible=false"):
            self._evaluate(deployments=deployments)

    def test_artifact_drift_fails_closed(self):
        prediction = dict(self.prediction)
        prediction["model_artifact_sha256"] = "9" * 64
        with self.assertRaisesRegex(MLBMoneylineFreshRuntimeError, "artifact mismatch"):
            self._evaluate(prediction=prediction)

    def test_runtime_probability_drift_fails_closed(self):
        def drift_engine(model_input):
            out = _engine(model_input)
            if model_input["side"] == "HOME":
                out["model_p"] = 0.59
            else:
                out["model_p"] = 0.41
            return out
        with patch(
            "sportsedge.mlb_moneyline_fresh_runtime.mlb_model_artifact_sha256",
            return_value=ARTIFACT,
        ), patch(
            "sportsedge.mlb_moneyline_fresh_runtime.engine_registry",
            return_value={"MONEYLINE": drift_engine},
        ):
            with self.assertRaisesRegex(MLBMoneylineFreshRuntimeError, "Model_P drift"):
                evaluate_fresh_runtime_hard_checks(
                    transition_readiness=self.readiness,
                    prediction=self.prediction,
                    capture=self.capture,
                    deployments=self.deployments,
                    now=self.now,
                )

    def test_incomplete_governance_documentation_fails_closed(self):
        readiness = dict(self.readiness)
        readiness["governance_documentation_complete"] = False
        with self.assertRaisesRegex(MLBMoneylineFreshRuntimeError, "not complete"):
            self._evaluate(transition_readiness=readiness)


if __name__ == "__main__":
    unittest.main()
