import unittest

from sportsedge.auto_runner import AutoRunReport, _convert as auto_convert, report_to_dict as auto_report_to_dict
from sportsedge.mlb_run_machine import _machine_result
from sportsedge.prediction_journal import build_prediction_journal_record
from sportsedge.unified_card import UnifiedCardResult


class MLBSportsbookProvenanceTests(unittest.TestCase):
    def _unified(self):
        return UnifiedCardResult(
            "822696", "PITCHER_K", "20", 5.5, "OVER", -119,
            0.61, "PASS", "ok",
            engine_version="mlb_pitcher_joint_empirical_v2",
            seed_policy="identity-derived-v1",
            mc_paths=1000,
            book_key="draftkings",
            sportsbook="DraftKings",
            quote_retrieved_at="2026-08-25T10:00:00+00:00",
            offer_id="offer-123",
        )

    def test_auto_report_preserves_quote_identity(self):
        row = auto_convert(0, self._unified())
        report = AutoRunReport(
            slate_date_ct="2026-08-25",
            generated_at_utc="2026-08-25T10:01:00+00:00",
            run_status="PASS",
            card_status="PASS",
            results=(row,),
            coverage_slots=(),
            source_failures=(),
            market_surface_version="test",
        )
        payload = auto_report_to_dict(report)
        saved = payload["results"][0]
        self.assertEqual(saved["book_key"], "draftkings")
        self.assertEqual(saved["sportsbook"], "DraftKings")
        self.assertEqual(saved["quote_retrieved_at"], "2026-08-25T10:00:00+00:00")
        self.assertEqual(saved["offer_id"], "offer-123")

    def test_prediction_journal_freezes_quote_identity(self):
        row = auto_convert(0, self._unified())
        payload = {
            "mode": "AUTOMATIC",
            "slate_date_ct": "2026-08-25",
            "generated_at_utc": "2026-08-25T10:01:00+00:00",
            "run_status": "PASS",
            "card_status": "PASS",
            "results": [row.__dict__],
        }
        journal = build_prediction_journal_record(payload)
        self.assertIsNotNone(journal)
        saved = journal["predictions"][0]
        self.assertEqual(saved["book_key"], "draftkings")
        self.assertEqual(saved["sportsbook"], "DraftKings")
        self.assertEqual(saved["quote_retrieved_at"], "2026-08-25T10:00:00+00:00")
        self.assertEqual(saved["offer_id"], "offer-123")

    def test_run_it_conversion_preserves_quote_identity(self):
        row = _machine_result(0, auto_convert(0, self._unified()))
        self.assertEqual(row.book_key, "draftkings")
        self.assertEqual(row.sportsbook, "DraftKings")
        self.assertEqual(row.quote_retrieved_at, "2026-08-25T10:00:00+00:00")
        self.assertEqual(row.offer_id, "offer-123")


if __name__ == "__main__":
    unittest.main()
