import json
import tempfile
import unittest
from pathlib import Path

from scripts.settle_market_maker_candidate_ledger_v2 import main


class SettlementV2Tests(unittest.TestCase):
    def test_empty_ledger_keeps_roi_primary_and_clv_process_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "archive"
            ledger = root / "ledger"
            out = root / "report.json"
            archive.mkdir(parents=True)
            ledger.mkdir(parents=True)
            rc = main([
                "--policy", "config/market_maker_radar_v2.json",
                "--archive-root", str(archive),
                "--ledger-root", str(ledger),
                "--out", str(out),
                "--now", "2026-09-14T12:00:00Z",
            ])
            self.assertEqual(rc, 0)
            payload = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(payload["primary_metric"], "REALIZED_ROI_ON_FILLED_WAGERS")
            self.assertEqual(payload["research_only_primary_metric_when_no_fills"], "PERSISTED_PRICE_FLAT_1U_ROI")
            self.assertEqual(payload["process_metric"], "CLV")
            self.assertEqual(payload["clv_role"], "DETECTOR_PROCESS_CHECK_NOT_EDGE_VALIDATION")
            self.assertEqual(payload["offered_price_roi_role"], "OPTIMISTIC_DIAGNOSTIC_ONLY_NOT_PRIMARY")
            self.assertFalse(payload["automatic_wager_authority"])
            self.assertEqual(payload["evaluation_checkpoints"]["filled_n"], [100, 250, 500, 1000])


if __name__ == "__main__":
    unittest.main()
