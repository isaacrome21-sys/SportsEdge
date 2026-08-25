import unittest

from sportsedge.auto_runner import AutoRunReport


class AutoRunReportConstructionTests(unittest.TestCase):
    def test_keyword_construction_is_supported(self):
        report = AutoRunReport(
            slate_date_ct="2026-08-25",
            generated_at_utc="2026-08-25T03:00:00+00:00",
            run_status="READY",
            card_status="NO_BETS",
            results=(),
            coverage_slots=(),
            source_failures=(),
            market_surface_version="test",
        )
        self.assertEqual(report.run_status, "READY")

    def test_positional_construction_is_rejected(self):
        with self.assertRaises(TypeError):
            AutoRunReport(
                "2026-08-25",
                "2026-08-25T03:00:00+00:00",
                "READY",
                "NO_BETS",
                (),
                (),
                (),
                "test",
            )


if __name__ == "__main__":
    unittest.main()
