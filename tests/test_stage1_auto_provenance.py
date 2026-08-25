import unittest

from sportsedge.auto_runner import AutoCardResult, AutoRunReport, _convert, report_to_dict
from sportsedge.unified_card import UnifiedCardResult


class Stage1AutoProvenanceTests(unittest.TestCase):
    def test_existing_positional_auto_card_constructor_remains_compatible(self):
        row = AutoCardResult(
            7, "1", "MONEYLINE", "10", 0.0, "HOME", -110,
            0.51, "PASS", "ok", None, None, None, None,
        )
        self.assertIsNone(row.model_input_hash)
        self.assertIsNone(row.distribution_sha256)
        self.assertIsNone(row.readout_sha256)
        self.assertIsNone(row.readout_version)

    def test_convert_and_report_preserve_stage1_provenance(self):
        hashes = {
            "model_input_hash": "a" * 64,
            "distribution_sha256": "b" * 64,
            "readout_sha256": "c" * 64,
            "readout_version": "mlb_v7_game_readout_v1",
        }
        unified = UnifiedCardResult(
            "1", "TOTALS", "1", 8.5, "OVER", -105,
            0.53, "PASS", "ok", None, 0.5, 0.03, 0.02,
            hashes["model_input_hash"], hashes["distribution_sha256"],
            hashes["readout_sha256"], hashes["readout_version"],
        )
        auto = _convert(7, unified)
        report = AutoRunReport(
            slate_date_ct="2026-08-25",
            generated_at_utc="2026-08-25T10:25:00+00:00",
            run_status="COMPLETE",
            card_status="PASS",
            results=(auto,),
            coverage_slots=(),
            source_failures=(),
            market_surface_version="test",
        )
        payload = report_to_dict(report)

        self.assertEqual(auto.source_index, 7)
        for key, value in hashes.items():
            with self.subTest(key=key):
                self.assertEqual(getattr(auto, key), value)
                self.assertEqual(payload["results"][0][key], value)


if __name__ == "__main__":
    unittest.main()
