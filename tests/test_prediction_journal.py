import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from sportsedge.mlb_run_machine import MLBMachineResult, _machine_result
from sportsedge.prediction_journal import (
    JOURNAL_SCHEMA_VERSION,
    LEGACY_JOURNAL_SCHEMA_VERSIONS,
    PredictionJournalError,
    read_prediction_journal,
    write_prediction_journal,
)


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
                    "block_reason": "price missing",
                },
            ],
            "source_failures": [],
        }

    def reset_prop_payload(self, market="HITS"):
        return {
            "slate_date_ct": "2026-08-25",
            "generated_at_utc": "2026-08-25T10:30:00+00:00",
            "run_status": "PASS",
            "card_status": "PASS",
            "results": [
                {
                    "source_index": 0,
                    "game_id": "777",
                    "market": market,
                    "entity_id": "10",
                    "line": 0.5,
                    "side": "OVER",
                    "american_odds": -110,
                    "model_p": 0.53,
                    "bet_status": "PASS",
                    "reason": "ok",
                    "model_input_hash": "a" * 64,
                    "engine_version": (
                        "mlb_pitcher_joint_empirical_v2"
                        if market == "PITCHER_BB"
                        else "mlb_hitter_joint_empirical_v3"
                    ),
                    "seed_policy": (
                        "analytic_empirical_joint_start_rows"
                        if market == "PITCHER_BB"
                        else "analytic_weighted_empirical_joint_game_rows"
                    ),
                    "mc_paths": 0,
                }
            ],
            "source_failures": [],
        }

    def test_modeled_and_blocked_rows_are_written_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = write_prediction_journal(self.payload(), root=tmp)
            self.assertIsNotNone(result)
            self.assertTrue(result.created)
            self.assertEqual(result.prediction_count, 3)
            path = Path(result.path)
            self.assertTrue(path.exists())
            self.assertEqual(path.parent.name, "2026-08-25")
            self.assertIn(result.journal_sha256, path.name)

            record = json.loads(path.read_text())
            self.assertEqual(record["schema_version"], JOURNAL_SCHEMA_VERSION)
            self.assertEqual(record["prediction_count"], 3)
            self.assertEqual(
                [row["bet_status"] for row in record["predictions"]],
                ["PASS", "OFFICIAL_BET", "BLOCKED"],
            )
            priced = [row for row in record["predictions"] if row.get("model_p") is not None]
            self.assertEqual({row["distribution_sha256"] for row in priced}, {"b" * 64})
            blocked = record["predictions"][2]
            self.assertEqual(blocked["block_reason"], "price missing")
            self.assertNotIn("reason", blocked)
            self.assertEqual(record["decision_counts"]["BLOCKED"], 1)
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
            self.assertEqual(len(list(Path(tmp).rglob("*.json"))), 1)

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

    def test_reset_props_persist_full_corrected_engine_identity(self):
        for market in ("HITS", "TOTAL_BASES", "PITCHER_BB"):
            with self.subTest(market=market), tempfile.TemporaryDirectory() as tmp:
                result = write_prediction_journal(self.reset_prop_payload(market), root=tmp)
                record = json.loads(Path(result.path).read_text())
                row = record["predictions"][0]
                self.assertEqual(row["model_input_hash"], "a" * 64)
                self.assertTrue(row["engine_version"])
                self.assertTrue(row["seed_policy"])
                self.assertEqual(row["mc_paths"], 0)

    def test_reset_prop_missing_engine_identity_is_rejected(self):
        for field in ("model_input_hash", "engine_version", "seed_policy", "mc_paths"):
            payload = self.reset_prop_payload("HITS")
            payload["results"][0][field] = None
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(PredictionJournalError, field):
                    write_prediction_journal(payload, root=tmp)

    def test_reset_prop_malformed_mc_paths_is_rejected(self):
        payload = self.reset_prop_payload("TOTAL_BASES")
        payload["results"][0]["mc_paths"] = 1.5
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(PredictionJournalError, "mc_paths"):
                write_prediction_journal(payload, root=tmp)

    def test_priced_blocked_row_is_preserved_with_provenance(self):
        payload = self.payload()
        row = payload["results"][0]
        row["bet_status"] = "BLOCKED"
        row["block_reason"] = "promotion evidence required"
        with tempfile.TemporaryDirectory() as tmp:
            result = write_prediction_journal(payload, root=tmp)
            record = json.loads(Path(result.path).read_text())
            blocked = record["predictions"][0]
            self.assertEqual(blocked["bet_status"], "BLOCKED")
            self.assertEqual(blocked["model_p"], 0.53)
            self.assertEqual(blocked["model_input_hash"], "a" * 64)
            self.assertEqual(blocked["block_reason"], "promotion evidence required")

    def test_unpriced_blocked_rows_create_a_journal(self):
        payload = self.payload()
        for i, row in enumerate(payload["results"]):
            row["model_p"] = None
            row.pop("edge", None)
            row["bet_status"] = "BLOCKED"
            row["block_reason"] = f"blocked {i}"
        with tempfile.TemporaryDirectory() as tmp:
            result = write_prediction_journal(payload, root=tmp)
            self.assertIsNotNone(result)
            record = json.loads(Path(result.path).read_text())
            self.assertEqual(record["prediction_count"], 3)
            self.assertEqual(record["decision_counts"]["BLOCKED"], 3)
            self.assertTrue(all(row["model_p"] is None for row in record["predictions"]))

    def test_no_journalable_rows_do_not_create_a_journal(self):
        payload = self.payload()
        for row in payload["results"]:
            row["model_p"] = None
            row.pop("edge", None)
            row["bet_status"] = "NO_ENGINE"
        with tempfile.TemporaryDirectory() as tmp:
            result = write_prediction_journal(payload, root=tmp)
            self.assertIsNone(result)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_no_engine_cannot_carry_probability_or_edge(self):
        for field, value in (("model_p", 0.5), ("edge", 0.01)):
            payload = self.payload()
            row = payload["results"][0]
            row["bet_status"] = "NO_ENGINE"
            row["model_p"] = None
            row.pop("edge", None)
            row[field] = value
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(PredictionJournalError, "NO_ENGINE cannot carry"):
                    write_prediction_journal(payload, root=tmp)

    def test_v1_artifact_remains_readable_and_distinguishable(self):
        self.assertEqual(JOURNAL_SCHEMA_VERSION, "mlb_prediction_journal_v2")
        self.assertIn("mlb_prediction_journal_v1", LEGACY_JOURNAL_SCHEMA_VERSIONS)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(json.dumps({"schema_version": "mlb_prediction_journal_v1", "predictions": []}))
            record = read_prediction_journal(path)
            self.assertEqual(record["schema_version"], "mlb_prediction_journal_v1")
            self.assertNotIn("decision_counts", record)

    def test_canonical_machine_preserves_stage1_and_engine_provenance(self):
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
            engine_version="mlb_v7_shared_game_engine_v1",
            seed_policy="deterministic_distribution_readout",
            mc_paths=20000,
        )
        result = _machine_result(0, row)
        self.assertIsInstance(result, MLBMachineResult)
        self.assertEqual(result.source_index, 4)
        self.assertEqual(result.model_input_hash, "a" * 64)
        self.assertEqual(result.distribution_sha256, "b" * 64)
        self.assertEqual(result.readout_sha256, "c" * 64)
        self.assertEqual(result.readout_version, "mlb_v7_game_readout_v1")
        self.assertEqual(result.engine_version, "mlb_v7_shared_game_engine_v1")
        self.assertEqual(result.seed_policy, "deterministic_distribution_readout")
        self.assertEqual(result.mc_paths, 20000)

    def test_existing_machine_result_positional_constructor_remains_compatible(self):
        result = MLBMachineResult(
            0, "1", "MONEYLINE", "10", 0.0, "HOME", -110,
            0.51, "PASS", "ok", None, None, None, None,
        )
        self.assertIsNone(result.model_input_hash)
        self.assertIsNone(result.distribution_sha256)
        self.assertIsNone(result.readout_sha256)
        self.assertIsNone(result.readout_version)
        self.assertIsNone(result.engine_version)
        self.assertIsNone(result.seed_policy)
        self.assertIsNone(result.mc_paths)


if __name__ == "__main__":
    unittest.main()
