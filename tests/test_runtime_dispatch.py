import json
import tempfile
import unittest
from pathlib import Path

from sportsedge.engine_registry import EngineDispatchError, hits_engine_adapter
from sportsedge.runtime import RuntimeInputError, result_to_dict, run_payload


def model_input(side="OVER", line=0.5):
    return {
        "build_hash": "a" * 64,
        "game_id": "game-1",
        "market": "HITS",
        "entity_id": "batter-1",
        "line": line,
        "side": side,
        "lineup_status": "CONFIRMED",
        "require_confirmed_lineup": True,
        "features": {"b_rate": 0.31, "p_rate": 0.27, "pa_pool": [3, 4, 4, 4, 5]},
    }


def quote(*, side="OVER", line=0.5, odds=100, retrieved="2026-08-10T20:00:00Z", ttl=300):
    return {
        "game_id": "game-1",
        "market": "HITS",
        "entity_id": "batter-1",
        "line": line,
        "side": side,
        "american_odds": odds,
        "retrieved_at": retrieved,
        "ttl_seconds": ttl,
    }


def payload(q=None, mi=None):
    return {
        "ingestion_now": "2026-08-10T20:01:00Z",
        "finalization_now": "2026-08-10T20:01:10Z",
        "min_edge": 0.0,
        "kelly_multiplier": 0.25,
        "candidates": [{"model_input": mi or model_input(), "quote": q or quote()}],
    }


def registry(path: Path, *, eligible: bool, stage: str):
    path.write_text(json.dumps({
        "schema_version": 1,
        "markets": {"HITS": {"eligible": eligible, "stage": stage, "reason": "test"}},
    }), encoding="utf-8")


class RuntimeDispatchTests(unittest.TestCase):
    def test_hits_adapter_is_deterministic_and_common_schema(self):
        a = hits_engine_adapter(model_input())
        b = hits_engine_adapter(model_input())
        self.assertEqual(a, b)
        self.assertEqual(a["market"], "HITS")
        self.assertEqual(a["game_id"], "game-1")
        self.assertTrue(0 <= a["model_p"] <= 1)

    def test_hits_under_is_complement_of_same_over_paths(self):
        over = hits_engine_adapter(model_input("OVER"))["model_p"]
        under = hits_engine_adapter(model_input("UNDER"))["model_p"]
        self.assertAlmostEqual(over + under, 1.0, places=12)

    def test_unsupported_hits_line_rejected(self):
        with self.assertRaises(EngineDispatchError):
            hits_engine_adapter(model_input(line=3.5))

    def test_checked_in_registry_blocks_hits_even_with_positive_edge(self):
        result = run_payload(payload())[0]
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIsNone(result.model_p)  # binding failure does not leak an official-looking probability
        self.assertIn("deployment not eligible", result.reason)

    def test_deployed_test_registry_can_reach_truth_gate(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            registry(p, eligible=True, stage="DEPLOYED")
            result = run_payload(payload(), registry_path=p)[0]
            self.assertIn(result.bet_status, ("OFFICIAL_BET", "PASS"))
            self.assertIsNotNone(result.model_p)
            doc = result_to_dict(result)
            self.assertIn("implied_probability", doc["decision"])
            self.assertIn("ev_per_dollar", doc["decision"])

    def test_quote_timestamp_string_is_parsed_and_double_ttl_blocks_final_stale(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            registry(p, eligible=True, stage="DEPLOYED")
            x = payload(q=quote(retrieved="2026-08-10T19:56:30Z", ttl=300))
            # Age 270s at ingestion, 310s at finalization.
            x["ingestion_now"] = "2026-08-10T20:01:00Z"
            x["finalization_now"] = "2026-08-10T20:01:40Z"
            result = run_payload(x, registry_path=p)[0]
            self.assertEqual(result.bet_status, "BLOCKED")
            self.assertIn("price is stale", result.reason)

    def test_candidate_binding_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "registry.json"
            registry(p, eligible=True, stage="DEPLOYED")
            q = quote()
            q["entity_id"] = "wrong-batter"
            result = run_payload(payload(q=q), registry_path=p)[0]
            self.assertEqual(result.bet_status, "BLOCKED")
            self.assertIn("candidate mismatch: entity_id", result.reason)

    def test_naive_pipeline_timestamp_rejected_before_run(self):
        x = payload()
        x["ingestion_now"] = "2026-08-10T20:01:00"
        with self.assertRaises(RuntimeInputError):
            run_payload(x)

    def test_invalid_risk_controls_fail_closed(self):
        for field, value in (("min_edge", float("nan")), ("kelly_multiplier", 1.1), ("kelly_multiplier", True)):
            x = payload()
            x[field] = value
            with self.subTest(field=field, value=value):
                with self.assertRaises(RuntimeInputError):
                    run_payload(x)


if __name__ == "__main__":
    unittest.main()
