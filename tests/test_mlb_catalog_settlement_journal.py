from pathlib import Path
import tempfile
import unittest

from sportsedge.mlb_catalog_settlement_journal import write_catalog_prediction_settlement


class MLBCatalogSettlementJournalTests(unittest.TestCase):
    def _record(self):
        return {
            "schema_version": "mlb_catalog_prediction_settlement_v1",
            "prediction_journal_schema_version": "mlb_prediction_journal_v1",
            "prediction_journal_sha256": "a" * 64,
            "source_report_sha256": "b" * 64,
            "slate_date_ct": "2026-08-25",
            "prediction_generated_at_utc": "2026-08-25T10:00:00+00:00",
            "settled_at_utc": "2026-08-25T12:00:00+00:00",
            "prediction_count": 1,
            "resolved_count": 1,
            "unresolved_count": 0,
            "win_count": 1,
            "loss_count": 0,
            "push_count": 0,
            "settlement_complete": True,
            "outcomes": [{"market": "PITCHER_K", "settlement_result": "WIN"}],
        }

    def test_duplicate_write_is_idempotent_and_never_overwrites(self):
        record = self._record()
        with tempfile.TemporaryDirectory() as tmp:
            first = write_catalog_prediction_settlement(record, root=tmp)
            second = write_catalog_prediction_settlement(record, root=tmp)
            self.assertTrue(first.created)
            self.assertFalse(second.created)
            self.assertEqual(first.path, second.path)
            original = Path(first.path).read_bytes()

            changed = dict(record)
            changed["settled_at_utc"] = "2026-08-25T12:05:00+00:00"
            third = write_catalog_prediction_settlement(changed, root=tmp)
            self.assertTrue(third.created)
            self.assertNotEqual(first.path, third.path)
            self.assertEqual(Path(first.path).read_bytes(), original)

    def test_counter_mismatch_is_rejected(self):
        record = self._record()
        record["resolved_count"] = 0
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "counters mismatch"):
                write_catalog_prediction_settlement(record, root=tmp)


if __name__ == "__main__":
    unittest.main()
