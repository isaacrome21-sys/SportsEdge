import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from sportsedge.mlb_run_machine import MLBMachineResult, _machine_result
from sportsedge.prediction_journal import PredictionJournalError, write_prediction_journal


class PredictionJournalTests(unittest.TestCase):
    def payload(self):
        shared_distribution = "b" * 64
        return {
            "slate_date_ct": "2026-08-25",
            "generated_at_utc": "2026-08-25T10:30:00+00:00",
            "run_status": "PASS",
            "card_status": "PASS",
            "results": [
                {
                    "source_index": 0,
                    "game_id": "777",
                    "market": "MONEYLINE",
                    "entity_id": "10",
                    "line": 0.0,
                    "side": "HOME",
                    "american_odds": -110,
                    "model_p": 0.53,
                    "bet_status": "PASS",
                    "reason": "ok",
                    "model_input_hash": "a" * 64,
                    "distribution_sha256": shared_distribution,
                    "readout_sha256": "c" * 64,
                    "readout_version": "mlb_v7_game_readout_v1",
                },
                {
                    "source_index": 1,
                    "game_id": "777",
                    "market": "TOTALS",
                    "entity_id": "777",
                    "line": 8.5,
                    "side": "OVER",
                    "american_odds": 100,
                    "model_p": 0.57,
                    "bet_status": "OFFICIAL_BET",
                    "reason": "ok",
                    "model_input_hash": "a" * 64,
                    "distribution_sha256": shared_distribution,
                    "readout_sha256": "d" * 64,
                    "readout_version": "mlb_v7_game_readout_v1",
                },
                {
                    "source_index": 2,
                    "game_id": "777",
                    "market": "RUN_LINE",
                    "entity_id": "10",
                    "line": -1.5,
                    "side": "HOME",
                    "american_odds": 120,
                    "model_p": None,
                    "bet_status": "BLOCKED",
                    "reason": "price missing",
                },
            ],
            "source_failures": [],
        }

    def test_modeled_rows_are_written_content_addressed_and_blocked_rows_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = write_prediction_journal(self.payload(), root=tmp)
            self.assertIsNotNone(result)
            self.assertTrue(result.created)
            self.assertEqual(result.prediction_count, 2)
            path = Path(result.path)
            self.assertTrue(path.exists())
            self.assertEqual(path.parent.name, "2026-08-25")
            self.assertIn(result.journal_sha256, path.name)

            record = json.loads(path.read_text())
            self.assertEqual(record["prediction_count"], 2)
            self.assertEqual([row["bet_status"] for row in record["predictions"]], ["PASS", "OFFICIAL_BET"])
            self.assertEqual(
                {row["distribution_sha256"] for row in record["predictions"]},
                {"b" * 64},
            )
            self.assertEqual(record["source_report_sha256"], result.source_report_sha256)

    def test_exact_duplicate_is_idempotent_and_never_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = write_prediction_journal(self.payload(), root=tmp)
            original = Path(first.path).read_bytes()
            second = write_prediction_journal(self.payload(), root=tmp)
            self.assertEqual(first.path, second.path)
            self.assertEqual(first.journal_sha256, second.journal_sha256)
            self.assertFalse(second.created)
            self.assertEqual(Path(first.path).read_bytes(), original)

    def test_changed_prediction_creates_new_file_instead_of_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            first_payload = self.payload()
            first = write_prediction_journal(first_payload, root=tmp)
            second_payload = self.payload()
            second_payload["results"][0]["model_p"] = 0.54
            second = write_prediction_journal(second_payload, root=tmp)
            self.assertNotEqual(first.path, second.path)
            self.assertNotEqual(first.journal_sha256, second.journal_sha256)
            self.assertTrue(Path(first.path).exists())
            self.assertTrue(Path(second.path).exists())

    def test_stage1_game_prediction_requires_full_provenance(self):
        payload = self.payload()
        payload["results"][0]["distribution_sha256"] = None
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PredictionJournalError, "distribution_sha256"):
                write_prediction_journal(payload, root=tmp)

    def test_modeled_blocked_row_is_rejected(self):
        payload = self.payload()
        payload["results"][0]["bet_status"] = "BLOCKED"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PredictionJournalError, "lacks BET/PASS decision"):
                write_prediction_journal(payload, root=tmp)

    def test_no_modeled_rows_do_not_create_a_journal(self):
        payload = self.payload()
        for row in payload["results"]:
            row["model_p"] = None
            row["bet_status"] = "BLOCKED"
        with tempfile.TemporaryDirectory() as tmp:
            result = write_prediction_journal(payload, root=tmp)
            self.assertIsNone(result)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_canonical_machine_preserves_stage1_provenance(self):
        row = SimpleNamespace(
            source_index=4,
            game_id="777",
            market="TOTALS",
            entity_id="777",
            line=8.5,
            side="OVER",
            american_odds=-105,
            model_p=0.53,
            bet_status="PASS",
            reason="ok",
            shadow_status=None,
            implied_probability=0.5,
            edge=0.03,
            ev_per_dollar=0.02,
            model_input_hash="a" * 64,
            distribution_sha256="b" * 64,
            readout_sha256="c" * 64,
            readout_version="mlb_v7_game_readout_v1",
        )
        result = _machine_result(0, row)
        self.assertIsInstance(result, MLBMachineResult)
        self.assertEqual(result.source_index, 4)
        self.assertEqual(result.model_input_hash, "a" * 64)
        self.assertEqual(result.distribution_sha256, "b" * 64)
        self.assertEqual(result.readout_sha256, "c" * 64)
        self.assertEqual(result.readout_version, "mlb_v7_game_readout_v1")

    def test_existing_machine_result_positional_constructor_remains_compatible(self):
        result = MLBMachineResult(
            0, "1", "MONEYLINE", "10", 0.0, "HOME", -110,
            0.51, "PASS", "ok", None, None, None, None,
        )
        self.assertIsNone(result.model_input_hash)
        self.assertIsNone(result.distribution_sha256)
        self.assertIsNone(result.readout_sha256)
        self.assertIsNone(result.readout_version)


if __name__ == "__main__":
    unittest.main()
