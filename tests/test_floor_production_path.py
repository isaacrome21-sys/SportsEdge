from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from sportsedge.orchestrator import run_candidate


UTC = timezone.utc
NOW = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)


def _quote(market: str, entity_id: str, side: str, odds: int) -> dict[str, object]:
    return {
        "game_id": "fixture-game",
        "period": "FG",
        "market": market,
        "entity_id": entity_id,
        "line": 0.5,
        "side": side,
        "american_odds": odds,
        "book_key": "fixture-book",
        "is_alternate": False,
        "retrieved_at": NOW,
        "ttl_seconds": 300,
    }


def _config() -> dict[str, object]:
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
            "edge_floors": {},
        }
    }


def _config_with_fixture_floor(market: str) -> dict[str, object]:
    config = _config()
    config["truth_gate"]["edge_floors"][market] = {
        "status": "FROZEN",
        "value_probability_points": 0.03,
        "method_version": "FIXTURE_ONLY_V1",
        "evidence": {
            "evidence_sha256": "a" * 64,
            "derivation_code_sha256": "b" * 64,
            "oos_cutoff_utc": "2026-01-01T00:00:00Z",
        },
        "frozen": {"frozen_by_commit": "c" * 40},
    }
    return config


class FloorProductionPathTests(unittest.TestCase):
    def test_missing_floor_blocks_official_but_preserves_identity_bound_model_candidate(self):
        cases = (
            ("HITS", "fixture-batter"),
            ("PITCHER_K", "fixture-pitcher"),
            ("MONEYLINE", "fixture-team"),
        )
        for market, entity_id in cases:
            with self.subTest(market=market), tempfile.TemporaryDirectory() as td:
                floor_path = Path(td) / "floors.json"
                floor_path.write_text(json.dumps(_config()), encoding="utf-8")
                calls: list[bool] = []

                def engine(_model_input):
                    calls.append(True)
                    return {"model_p": 0.60}

                result = run_candidate(
                    model_input={
                        "game_id": "fixture-game", "market": market, "entity_id": entity_id,
                        "line": 0.5, "side": "OVER",
                    },
                    quote=_quote(market, entity_id, "OVER", 100),
                    paired_quote=_quote(market, entity_id, "UNDER", -120),
                    deployment={"eligible": True, "stage": "DEPLOYED", "market": market},
                    engine_fn=engine,
                    ingestion_now=NOW,
                    finalization_now=NOW,
                    edge_floor_config_path=str(floor_path),
                )
                self.assertEqual(result.bet_status, "MODEL_CANDIDATE")
                self.assertEqual(result.model_p, 0.60)
                self.assertIn(f"ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:{market}", result.reason)
                self.assertIsNone(result.decision)
                self.assertEqual(calls, [True])

    def test_valid_fixture_floor_opens_real_orchestrator_path_and_is_applied(self):
        market = "HITS"
        entity_id = "fixture-batter"
        with tempfile.TemporaryDirectory() as td:
            floor_path = Path(td) / "floors.json"
            floor_path.write_text(json.dumps(_config_with_fixture_floor(market)), encoding="utf-8")
            calls: list[bool] = []

            def engine(_model_input):
                calls.append(True)
                return {"model_p": 0.70}

            result = run_candidate(
                model_input={
                    "game_id": "fixture-game", "market": market, "entity_id": entity_id,
                    "line": 0.5, "side": "OVER",
                },
                quote=_quote(market, entity_id, "OVER", 100),
                paired_quote=_quote(market, entity_id, "UNDER", -120),
                deployment={"eligible": True, "stage": "DEPLOYED", "market": market},
                engine_fn=engine,
                ingestion_now=NOW,
                finalization_now=NOW,
                edge_floor_config_path=str(floor_path),
            )
            self.assertEqual(calls, [True])
            self.assertEqual(result.reason, "ok")
            self.assertEqual(result.model_p, 0.70)
            self.assertIsNotNone(result.decision)
            self.assertGreater(result.decision.edge, 0.03)
            self.assertEqual(result.bet_status, "OFFICIAL_BET")


if __name__ == "__main__":
    unittest.main()
