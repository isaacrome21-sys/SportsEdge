from types import SimpleNamespace
import unittest
from unittest.mock import patch

from sportsedge.generic_card_pipeline import GenericCardResult
from sportsedge.orchestrator import RunResult, run_candidate
from sportsedge.unified_card import UnifiedCardResult, _convert, unified_result_to_dict


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
        self.assertIsNone(generic.readout_sha256)
        self.assertIsNone(unified.model_input_hash)

    @patch("sportsedge.orchestrator.decide_bet")
    @patch("sportsedge.orchestrator.multiplicative_devig")
    @patch("sportsedge.orchestrator.require_production_edge_floor")
    @patch("sportsedge.orchestrator.bind_candidate")
    @patch("sportsedge.orchestrator.double_ttl_gate")
    def test_run_candidate_captures_engine_provenance(
        self, _ttl, _bind, floor, devig, decide,
    ):
        floor.return_value = SimpleNamespace(value_probability_points=0.0)
        devig.return_value = SimpleNamespace(candidate_fair_probability=0.5)
        decide.return_value = SimpleNamespace(bet_status="PASS", push_probability=0.0)
        hashes = {
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_v7_game_readout_v1",
        }

        result = run_candidate(
            model_input={
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME",
            },
            quote={"american_odds": -110},
            paired_quote={"american_odds": 100},
            deployment={"eligible": True},
            engine_fn=lambda _: {
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME", "model_p": 0.51, "push_p": 0.0,
                **hashes,
            },
            ingestion_now=SimpleNamespace(),
            finalization_now=SimpleNamespace(),
        )

        self.assertEqual(result.bet_status, "PASS")
        self.assertEqual(result.model_input_hash, hashes["model_input_hash"])
        self.assertEqual(result.distribution_sha256, hashes["distribution_sha256"])
        self.assertEqual(result.readout_sha256, hashes["readout_sha256"])
        self.assertEqual(result.readout_version, hashes["readout_version"])

    @patch("sportsedge.orchestrator.bind_candidate")
    @patch("sportsedge.orchestrator.double_ttl_gate")
    def test_malformed_engine_provenance_fails_closed(self, _ttl, _bind):
        result = run_candidate(
            model_input={
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME",
            },
            quote={"american_odds": -110},
            paired_quote={"american_odds": 100},
            deployment={"eligible": True},
            engine_fn=lambda _: {
                "game_id": "1", "market": "MONEYLINE", "entity_id": "10",
                "line": 0.0, "side": "HOME", "model_p": 0.51,
                "distribution_sha256": "not-a-sha",
            },
            ingestion_now=SimpleNamespace(),
            finalization_now=SimpleNamespace(),
        )
        self.assertEqual(result.bet_status, "BLOCKED")
        self.assertIsNone(result.model_p)
        self.assertIn("malformed distribution_sha256", result.reason)

    def test_unified_serialization_preserves_provenance(self):
        hashes = {
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_v7_game_readout_v1",
        }
        generic = GenericCardResult(
            "1", "TOTALS", "1", 8.5, "OVER", -105,
            0.53, "PASS", "ok", None, 0.5, 0.03, 0.02,
            hashes["model_input_hash"], hashes["distribution_sha256"],
            hashes["readout_sha256"], hashes["readout_version"],
        )
        unified = _convert(generic)
        payload = unified_result_to_dict(unified)
        for key, value in hashes.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(unified, key), value)
                self.assertEqual(payload[key], value)


if __name__ == "__main__":
    unittest.main()
