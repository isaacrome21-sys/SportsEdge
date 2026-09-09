from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.edge_floors import EdgeFloorError
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID
from sportsedge.sports.nfl.readiness import NFLReadinessError, run_nfl_ready
from sportsedge.sports.nfl.run_machine import NFLMachineReport, NFLMachineResult


CODE_SHA = "a" * 40
SOURCE_SHA = "b" * 64
ARTIFACT_SHA = "c" * 64
NOW = datetime(2026, 9, 9, 15, 0, tzinfo=timezone.utc)


def _artifact():
    return {
        "code_git_sha": CODE_SHA,
        "source_manifest_sha256": SOURCE_SHA,
    }


def _registry(*, deployed=("moneyline",)):
    markets = {}
    for market in ("moneyline", "spread", "total"):
        is_deployed = market in deployed
        markets[market] = {
            "stage": "DEPLOYED" if is_deployed else "HISTORICAL_VALIDATION",
            "eligible": is_deployed,
            "reason": "fixture",
        }
    return {
        "schema_version": 9,
        "sport": "nfl",
        "model_id": PRODUCTION_NFL_M2_MODEL_ID,
        "feature_contract": NFL_M2_FEATURE_CONTRACT,
        "code_git_sha": CODE_SHA,
        "source_sha256": "d" * 64,
        "source_manifest_sha256": SOURCE_SHA,
        "markets": markets,
        "deployed_markets": sorted(deployed),
    }


def _floor_config(*, keys=("NFL_MONEYLINE",)):
    floors = {}
    for key in keys:
        floors[key] = {
            "status": "FROZEN",
            "value_probability_points": 0.03,
            "method_version": "FIXTURE_ONLY_V1",
            "evidence": {
                "evidence_sha256": "e" * 64,
                "derivation_code_sha256": "f" * 64,
                "oos_cutoff_utc": "2026-01-01T00:00:00Z",
            },
            "frozen": {"frozen_by_commit": "1" * 40},
        }
    return {
        "truth_gate": {
            "schema_version": 2,
            "production": {
                "fail_closed": True,
                "allow_cli_floor_override": False,
                "require_frozen_floor_for_eligible_market": True,
            },
            "devig_policy": {
                "policy_id": "EDGE_FLOOR_DEVIG_V1",
                "status": "FROZEN_PRE_DERIVATION",
                "longshot_trigger_american_odds": 400,
                "longshot_trigger_rule": "EITHER_SIDE_AT_OR_ABOVE_POSITIVE_400",
                "sensitivity_methods": ["MULTIPLICATIVE_V1", "POWER_V1", "SHIN_V1"],
                "sensitivity_limit_absolute_probability_points": 0.01,
                "stable_candidate_estimator": "POWER_V1",
                "longshot_candidate_estimator": "POWER_V1",
                "haircut_probability_points": 0.0,
                "aggregation_rule": "ESTIMATOR_ONLY_NO_MINIMUM_ACROSS_METHODS",
                "sensitivity_failure": "BLOCK",
            },
            "edge_floors": floors,
        }
    }


def _row(*, market="MONEYLINE", side="HOME", model_p=0.70, fair=0.50, odds=100.0):
    return NFLMachineResult(
        game_id="g1", market=market, side=side, line=None,
        american_odds=odds, model_p=model_p, push_p=0.0,
        fair_market_p=fair, raw_implied_p=0.50, hold=0.0,
        edge=model_p - fair, ev_per_dollar=0.40,
        bet_status="BLOCKED", engine_status="PRICED",
        reason="NFL_PROMOTION_EVIDENCE_REQUIRED",
        model_artifact_sha256=ARTIFACT_SHA,
        model_code_git_sha=CODE_SHA,
        training_source_manifest_sha256=SOURCE_SHA,
        live_feature_source_manifest_sha256="2" * 64,
        live_feature_asof_ts=NOW.isoformat(), distribution_sha256="3" * 64,
        book_key="draftkings", sportsbook="DraftKings",
        quote_observed_at=NOW.isoformat(), provider_event_id="evt1",
    )


def _report(rows=None):
    rows = tuple(rows or (_row(), _row(side="AWAY", model_p=0.30, fair=0.50)))
    return NFLMachineReport(
        mode="MANUAL", generated_at_utc=NOW.isoformat(), run_status="BLOCKED",
        machine_version="NFL_RUN_MACHINE_V1", results=rows,
        summary={"quote_count": len(rows), "priced": len(rows), "stale": 0,
                 "blocked": len(rows), "official_bets": 0,
                 "markets_seen": sorted({r.market for r in rows}), "games_seen": ["g1"]},
        model_artifact_sha256=ARTIFACT_SHA, model_code_git_sha=CODE_SHA,
        training_source_manifest_sha256=SOURCE_SHA,
        live_feature_source_manifest_sha256="2" * 64,
        live_feature_asof_ts=NOW.isoformat(), quote_observed_at=NOW.isoformat(),
    )


class NFLReadinessTests(unittest.TestCase):
    def test_deployed_market_has_official_open_path(self):
        with tempfile.TemporaryDirectory() as td:
            floor = Path(td) / "floors.json"
            floor.write_text(json.dumps(_floor_config()), encoding="utf-8")
            with patch(
                "sportsedge.sports.nfl.readiness.run_nfl_machine",
                return_value=_report(),
            ) as engine:
                result = run_nfl_ready(
                    promotion_registry=_registry(), floor_path=floor,
                    model_artifact=_artifact(), expected_model_artifact_sha256=ARTIFACT_SHA,
                    runtime_code_git_sha=CODE_SHA, now=NOW,
                )
            engine.assert_called_once()
        home = next(r for r in result.results if r.side == "HOME")
        self.assertEqual(home.bet_status, "OFFICIAL_BET")
        self.assertEqual(home.reason, "TRUTH_GATE_RESOLVED")
        self.assertEqual(result.summary["official_bets"], 1)
        self.assertEqual(result.summary["floor_keys"], ["NFL_MONEYLINE"])
        self.assertFalse(result.summary["manual_eligible_toggle_required"])

    def test_missing_floor_stops_model_before_inference(self):
        with tempfile.TemporaryDirectory() as td:
            floor = Path(td) / "floors.json"
            floor.write_text(json.dumps(_floor_config(keys=())), encoding="utf-8")
            with patch("sportsedge.sports.nfl.readiness.run_nfl_machine") as engine:
                with self.assertRaisesRegex(
                    EdgeFloorError,
                    "ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:NFL_MONEYLINE",
                ):
                    run_nfl_ready(
                        promotion_registry=_registry(), floor_path=floor,
                        model_artifact=_artifact(), expected_model_artifact_sha256=ARTIFACT_SHA,
                        runtime_code_git_sha=CODE_SHA, now=NOW,
                    )
            engine.assert_not_called()

    def test_registry_cannot_deploy_for_different_artifact_code(self):
        registry = _registry()
        registry["code_git_sha"] = "9" * 40
        with self.assertRaisesRegex(NFLReadinessError, "CODE_BINDING_MISMATCH"):
            run_nfl_ready(
                promotion_registry=registry,
                model_artifact=_artifact(), expected_model_artifact_sha256=ARTIFACT_SHA,
                runtime_code_git_sha=CODE_SHA, now=NOW,
            )

    def test_stage_and_eligible_cannot_disagree(self):
        registry = _registry(deployed=())
        registry["markets"]["spread"]["eligible"] = True
        with self.assertRaisesRegex(NFLReadinessError, "STAGE_CONTRADICTION:spread"):
            run_nfl_ready(
                promotion_registry=registry,
                model_artifact=_artifact(), expected_model_artifact_sha256=ARTIFACT_SHA,
                runtime_code_git_sha=CODE_SHA, now=NOW,
            )


if __name__ == "__main__":
    unittest.main()
