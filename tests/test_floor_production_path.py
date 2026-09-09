from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from sportsedge.orchestrator import run_candidate


UTC = timezone.utc
NOW = datetime(2026, 9, 9, 15, 0, tzinfo=UTC)


def _quote(side: str, odds: int) -> dict[str, object]:
    return {
        "game_id": "fixture-game",
        "period": "FG",
        "market": "HITS",
        "entity_id": "fixture-batter",
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
                "sensitivity_methods": [
                    "MULTIPLICATIVE_V1",
                    "POWER_V1",
                    "SHIN_V1",
                ],
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


class FloorProductionPathTests(unittest.TestCase):
    def test_eligible_market_without_floor_blocks_before_engine_with_specific_reason(self):
        with tempfile.TemporaryDirectory() as td:
            floor_path = Path(td) / "floors.json"
            floor_path.write_text(json.dumps(_config()), encoding="utf-8")
            calls: list[bool] = []

            def engine(_model_input):
                calls.append(True)
                return {"model_p": 0.60}

            result = run_candidate(
                model_input={
                    "game_id": "fixture-game",
                    "market": "HITS",
                    "entity_id": "fixture-batter",
                    "line": 0.5,
                    "side": "OVER",
                },
                quote=_quote("OVER", 100),
                paired_quote=_quote("UNDER", -120),
                deployment={"eligible": True, "stage": "DEPLOYED"},
                engine_fn=engine,
                ingestion_now=NOW,
                finalization_now=NOW,
                edge_floor_config_path=str(floor_path),
            )

        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertEqual(
            result.reason,
            "EdgeFloorError: ELIGIBLE_MARKET_MISSING_OR_UNFROZEN_EDGE_FLOOR:HITS",
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
