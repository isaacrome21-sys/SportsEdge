from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sportsedge.edge_floors import EdgeFloorError
from sportsedge.football_prop_certification import (
    FootballPropCertificationError,
    assess_market_certification,
)
from sportsedge.football_prop_evidence import EVIDENCE_GROUPS
from sportsedge.football_prop_readiness import run_football_props_ready


ARTIFACT_SHA = "a" * 64
MARKET = "player_pass_yds"


def _evidence():
    return {
        "schema_version": "FOOTBALL_PROP_EVIDENCE_V1",
        "sport": "NFL",
        "groups": {
            group: {
                "status": "PASS",
                "evidence_sha256": "b" * 64,
                "model_artifact_sha256": ARTIFACT_SHA,
            }
            for group in EVIDENCE_GROUPS
        },
    }


def _certification(*, market=MARKET):
    return {
        "schema_version": "FOOTBALL_PROP_CERTIFICATION_V1",
        "sport": "NFL",
        "markets": {
            market: {
                "status": "PASS",
                "evidence_sha256": "c" * 64,
                "model_artifact_sha256": ARTIFACT_SHA,
                "observations": 250,
                "calibration": {"slope": 1.0, "intercept": 0.0, "ece": 0.01},
                "mean_clv": 0.01,
                "after_vig_roi": 0.03,
            }
        },
    }


def _floor_config(*, market=MARKET):
    floor_key = f"NFL_{market}"
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
            "edge_floors": {
                floor_key: {
                    "status": "FROZEN",
                    "value_probability_points": 0.03,
                    "method_version": "FIXTURE_ONLY_V1",
                    "evidence": {
                        "evidence_sha256": "d" * 64,
                        "derivation_code_sha256": "e" * 64,
                        "oos_cutoff_utc": "2026-01-01T00:00:00Z",
                    },
                    "frozen": {"frozen_by_commit": "f" * 40},
                }
            },
        }
    }


def _odds(market=MARKET):
    return {
        "events": [{
            "bookmakers": [{
                "markets": [{"key": market}]
            }]
        }]
    }


def _report(*, market=MARKET, fair_market_p=0.50):
    return {
        "sport": "NFL",
        "results": [{
            "sport": "NFL",
            "game_id": "g1",
            "provider_market": market,
            "model_artifact_sha256": ARTIFACT_SHA,
            "model_p": 0.70,
            "push_p": 0.0,
            "american_odds": 100,
            "fair_market_p": fair_market_p,
            "quote_fresh": True,
            "bet_status": "BLOCKED",
            "reason": "NFL_PROP_PROMOTION_EVIDENCE_REQUIRED",
        }],
        "summary": {"official_bets": 0},
    }


class FootballPropCertificationTests(unittest.TestCase):
    def test_numeric_pass_is_exact_artifact_bound(self):
        state = assess_market_certification(
            sport="NFL", provider_market=MARKET,
            model_artifact_sha256=ARTIFACT_SHA,
            registry=_certification(),
        )
        self.assertTrue(state["ready"])
        self.assertGreaterEqual(state["observations"], 200)

    def test_claimed_pass_cannot_hide_failed_calibration(self):
        registry = _certification()
        registry["markets"][MARKET]["calibration"]["ece"] = 0.04
        with self.assertRaisesRegex(
            FootballPropCertificationError,
            "FOOTBALL_PROP_CERTIFICATION_PASS_CONTRADICTION",
        ):
            assess_market_certification(
                sport="NFL", provider_market=MARKET,
                model_artifact_sha256=ARTIFACT_SHA,
                registry=registry,
            )

    def test_wrong_artifact_never_certifies(self):
        state = assess_market_certification(
            sport="NFL", provider_market=MARKET,
            model_artifact_sha256="9" * 64,
            registry=_certification(),
        )
        self.assertFalse(state["ready"])
        self.assertEqual(
            state["blockers"],
            [f"PROP_CERTIFICATION_ARTIFACT_MISMATCH:{MARKET}"],
        )

    def test_all_real_gates_have_an_official_open_path(self):
        with tempfile.TemporaryDirectory() as td:
            floor_path = Path(td) / "floors.json"
            floor_path.write_text(json.dumps(_floor_config()), encoding="utf-8")
            with patch(
                "sportsedge.football_prop_readiness.run_football_extended_props",
                return_value=_report(),
            ) as engine:
                result = run_football_props_ready(
                    sport="NFL",
                    expected_artifact_sha256=ARTIFACT_SHA,
                    odds_snapshot=_odds(),
                    evidence_registry=_evidence(),
                    certification_registry=_certification(),
                    floor_path=str(floor_path),
                )
            engine.assert_called_once()
            row = result["results"][0]
            self.assertTrue(row["official_eligible"])
            self.assertEqual(row["truth_gate_floor_key"], f"NFL_{MARKET}")
            self.assertEqual(row["bet_status"], "OFFICIAL_BET")
            self.assertEqual(result["summary"]["official_bets"], 1)
            self.assertTrue(result["evidence_resolution"]["can_promote"])
            self.assertFalse(
                result["certification_resolution"]["manual_eligible_toggle_required"]
            )

    def test_promotion_grade_missing_floor_blocks_before_model(self):
        empty = _floor_config()
        empty["truth_gate"]["edge_floors"] = {}
        with tempfile.TemporaryDirectory() as td:
            floor_path = Path(td) / "floors.json"
            floor_path.write_text(json.dumps(empty), encoding="utf-8")
            with patch(
                "sportsedge.football_prop_readiness.run_football_extended_props",
                return_value=_report(),
            ) as engine:
                with self.assertRaisesRegex(
                    EdgeFloorError,
                    f"ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:NFL_{MARKET}",
                ):
                    run_football_props_ready(
                        sport="NFL",
                        expected_artifact_sha256=ARTIFACT_SHA,
                        odds_snapshot=_odds(),
                        evidence_registry=_evidence(),
                        certification_registry=_certification(),
                        floor_path=str(floor_path),
                    )
            engine.assert_not_called()

    def test_one_sided_scorer_can_never_become_official(self):
        market = "player_anytime_td"
        with tempfile.TemporaryDirectory() as td:
            floor_path = Path(td) / "floors.json"
            floor_path.write_text(
                json.dumps(_floor_config(market=market)), encoding="utf-8"
            )
            with patch(
                "sportsedge.football_prop_readiness.run_football_extended_props",
                return_value=_report(market=market, fair_market_p=None),
            ):
                result = run_football_props_ready(
                    sport="NFL",
                    expected_artifact_sha256=ARTIFACT_SHA,
                    odds_snapshot=_odds(market),
                    evidence_registry=_evidence(),
                    certification_registry=_certification(market=market),
                    floor_path=str(floor_path),
                )
        row = result["results"][0]
        self.assertFalse(row["official_eligible"])
        self.assertEqual(row["bet_status"], "BLOCKED")
        self.assertEqual(row["reason"], "NFL_PROP_PAIRED_PRICE_REQUIRED")


if __name__ == "__main__":
    unittest.main()
