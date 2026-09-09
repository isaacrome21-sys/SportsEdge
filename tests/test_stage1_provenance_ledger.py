from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sportsedge.generic_card_pipeline import GenericCardResult
from sportsedge.orchestrator import RunResult, run_candidate
from sportsedge.runtime import result_to_dict
from sportsedge.unified_card import UnifiedCardResult, _convert, unified_result_to_dict


NOW = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


def _quote(odds: int) -> dict:
    return {
        "american_odds": odds,
        "book_key": "fixture-book",
        "sportsbook": "FIXTURE",
        "retrieved_at": NOW,
        "offer_id": f"fixture-{odds}",
    }


class Stage1ProvenanceLedgerTests(unittest.TestCase):
    def test_existing_positional_result_constructors_remain_compatible(self):
        run = RunResult("MONEYLINE", 0.51, "PASS", None, "ok")
        generic = GenericCardResult(
            "1", "MONEYLINE", "10", 0.0, "HOME", -110,
            0.51, "PASS", "ok", None, None, None, None,
        )
        unified = UnifiedCardResult(
            "1", "MONEYLINE", "10", 0.0, "HOME", -110,
            0.51, "PASS", "ok", None, None, None, None,
        )
        self.assertIsNone(run.distribution_sha256)
        self.assertIsNone(run.engine_version)
        self.assertIsNone(run.seed_policy)
        self.assertIsNone(run.mc_paths)
        self.assertIsNone(generic.readout_sha256)
        self.assertIsNone(generic.engine_version)
        self.assertIsNone(unified.model_input_hash)
        self.assertIsNone(unified.seed_policy)

    @patch("sportsedge.orchestrator.decide_bet")
    @patch("sportsedge.orchestrator.devig_with_policy")
    @patch("sportsedge.orchestrator.require_production_edge_floor")
    @patch("sportsedge.orchestrator.bind_candidate")
    @patch("sportsedge.orchestrator.double_ttl_gate")
    def test_run_candidate_captures_engine_provenance(
        self, _ttl, _bind, floor, priced, decide,
    ):
        floor.return_value = SimpleNamespace(value_probability_points=0.0)
        priced.return_value = SimpleNamespace(fair_probability_for_decision=0.5)
        decide.return_value = SimpleNamespace(bet_status="PASS", push_probability=0.0)
        provenance = {
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_v7_game_readout_v1",
            "engine_version": "mlb_hitter_joint_empirical_v3",
            "seed_policy": "analytic_weighted_empirical_joint_game_rows",
            "mc_paths": 0,
        }

        result = run_candidate(
            model_input={
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME",
            },
            quote=_quote(-110),
            paired_quote=_quote(100),
            deployment={"eligible": True},
            engine_fn=lambda _: {
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME", "model_p": 0.51, "push_p": 0.0,
                **provenance,
            },
            ingestion_now=NOW,
            finalization_now=NOW,
        )

        self.assertEqual(result.bet_status, "PASS")
        self.assertEqual(result.book_key, "fixture-book")
        self.assertEqual(result.sportsbook, "FIXTURE")
        self.assertEqual(result.quote_retrieved_at, NOW.isoformat())
        for key, value in provenance.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(result, key), value)

    @patch("sportsedge.orchestrator.bind_candidate")
    @patch("sportsedge.orchestrator.double_ttl_gate")
    @patch("sportsedge.orchestrator.require_production_edge_floor")
    def test_malformed_engine_provenance_fails_closed(self, _floor, _ttl, _bind):
        result = run_candidate(
            model_input={
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME",
            },
            quote=_quote(-110),
            paired_quote=_quote(100),
            deployment={"eligible": True},
            engine_fn=lambda _: {
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME", "model_p": 0.51,
                "distribution_sha256": "not-a-sha",
            },
            ingestion_now=NOW,
            finalization_now=NOW,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIsNone(result.model_p)
        self.assertIn("malformed distribution_sha256", result.reason)

    @patch("sportsedge.orchestrator.bind_candidate")
    @patch("sportsedge.orchestrator.double_ttl_gate")
    def test_invalid_mc_paths_fails_closed_before_decision(self, _ttl, _bind):
        result = run_candidate(
            model_input={
                "game_id": "1", "market": "HITS", "entity_id": "10",
                "line": 0.5, "side": "OVER",
            },
            quote=_quote(-110),
            paired_quote=_quote(-110),
            deployment={"eligible": False},
            engine_fn=lambda _: {
                "game_id": "1", "market": "HITS", "entity_id": "10",
                "line": 0.5, "side": "OVER", "model_p": 0.51,
                "model_input_hash": "a" * 64,
                "engine_version": "mlb_hitter_joint_empirical_v3",
                "seed_policy": "analytic_weighted_empirical_joint_game_rows",
                "mc_paths": -1,
            },
            ingestion_now=NOW,
            finalization_now=NOW,
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIsNone(result.model_p)
        self.assertIn("malformed mc_paths", result.reason)

    def test_direct_runtime_serialization_preserves_provenance(self):
        provenance = {
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_v7_game_readout_v1",
            "engine_version": "mlb_hitter_joint_empirical_v3",
            "seed_policy": "analytic_weighted_empirical_joint_game_rows",
            "mc_paths": 0,
        }
        run = RunResult(
            "HITS", 0.53, "PASS", None, "ok",
            model_input_hash=provenance["model_input_hash"],
            distribution_sha256=provenance["distribution_sha256"],
            readout_sha256=provenance["readout_sha256"],
            readout_version=provenance["readout_version"],
            engine_version=provenance["engine_version"],
            seed_policy=provenance["seed_policy"],
            mc_paths=provenance["mc_paths"],
        )
        payload = result_to_dict(run)
        for key, value in provenance.items():
            with self.subTest(key=key):
                self.assertEqual(payload[key], value)

    def test_unified_serialization_preserves_provenance(self):
        provenance = {
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_v7_game_readout_v1",
            "engine_version": "mlb_v7_shared_game_engine_v1",
            "seed_policy": "deterministic_distribution_readout",
            "mc_paths": 20000,
        }
        generic = GenericCardResult(
            "1", "TOTALS", "1", 8.5, "OVER", -105,
            0.53, "PASS", "ok", None, 0.5, 0.03, 0.02,
            provenance["model_input_hash"], provenance["distribution_sha256"],
            provenance["readout_sha256"], provenance["readout_version"],
            provenance["engine_version"], provenance["seed_policy"], provenance["mc_paths"],
        )
        unified = _convert(generic)
        payload = unified_result_to_dict(unified)
        for key, value in provenance.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(unified, key), value)
                self.assertEqual(payload[key], value)


if __name__ == "__main__":
    unittest.main()
