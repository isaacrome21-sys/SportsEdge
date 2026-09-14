import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_market_maker_radar_v2 import analyze, load_policy
from tests.test_market_maker_radar import row

POLICY = load_policy("config/market_maker_radar_v2.json")


def timed(base):
    item = dict(base)
    item.update({
        "provider_request_started_at": "2026-09-14T12:00:00Z",
        "provider_retrieved_at": "2026-09-14T12:00:02Z",
        "cross_book_retrieval_skew_seconds": 2.0,
        "leadership_timing_eligible": True,
        "timing_hygiene_version": "RADAR_TIMING_HYGIENE_V2",
        "provider_quote_age_seconds": None,
        "provider_quote_age_status": "UNKNOWN_PROVIDER_QUOTE_TIMESTAMP",
    })
    return item


class PolicyFreezeTests(unittest.TestCase):
    def test_signal_thresholds_are_frozen_before_first_lead_signal(self):
        freeze = POLICY["threshold_freeze"]
        self.assertEqual(freeze["status"], "FROZEN_BEFORE_FIRST_LEAD_LAG_SIGNAL")
        self.assertTrue(freeze["historical_reclassification_forbidden"])
        self.assertTrue(freeze["change_requires_new_policy_version"])
        self.assertEqual(freeze["frozen_fields"]["timing.lead_follow_window_seconds"], 900)
        self.assertEqual(freeze["frozen_fields"]["timing.max_cross_book_retrieval_skew_seconds"], 30)
        self.assertEqual(freeze["frozen_fields"]["alerts.stale_offer_fair_probability_gap_pp"], 1.0)


class TimingGateTests(unittest.TestCase):
    def test_old_or_timing_ineligible_rows_cannot_create_stale_signal(self):
        rows = [
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Home", price=-120),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Away", price=110),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=100),
            row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Away", price=-110),
        ]
        report = analyze(rows, POLICY)
        self.assertEqual(report["timing_eligible_row_count"], 0)
        self.assertEqual(report["stale_soft_price_count"], 0)
        self.assertEqual(report["lead_lag_signal_count"], 0)


class CandidateLedgerTests(unittest.TestCase):
    def test_first_stale_contract_creates_one_immutable_flat_1u_candidate(self):
        rows = [
            timed(row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Home", price=-120)),
            timed(row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="pinnacle", outcome="Away", price=110)),
            timed(row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Home", price=100)),
            timed(row(capture="c1", captured_at="2026-09-14T12:00:00Z", book="draftkings", outcome="Away", price=-110)),
            timed(row(capture="c2", captured_at="2026-09-14T12:05:00Z", book="pinnacle", outcome="Home", price=-120)),
            timed(row(capture="c2", captured_at="2026-09-14T12:05:00Z", book="pinnacle", outcome="Away", price=110)),
            timed(row(capture="c2", captured_at="2026-09-14T12:05:00Z", book="draftkings", outcome="Home", price=100)),
            timed(row(capture="c2", captured_at="2026-09-14T12:05:00Z", book="draftkings", outcome="Away", price=-110)),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = analyze(rows, POLICY, ledger_root=root)
            self.assertEqual(first["stale_soft_price_count"], 2)
            self.assertEqual(first["candidate_ledger_new_count"], 1)
            candidate = first["candidate_ledger_new"][0]
            self.assertEqual(candidate["source_family_id"], "PINNACLE_TO_DRAFTKINGS_STALE_PRICE_H2H_V1")
            candidate_path = root / candidate["path"]
            payload = json.loads(candidate_path.read_text())
            self.assertEqual(payload["flat_stake_units"], 1.0)
            self.assertEqual(payload["grading_status"], "PENDING_CLOSE")
            self.assertEqual(payload["validation_status"], "INSUFFICIENT")
            self.assertFalse(payload["automatic_wager_authority"])
            self.assertTrue(payload["manual_candidate_review_eligible"])
            before = candidate_path.read_bytes()

            second = analyze(rows, POLICY, ledger_root=root)
            self.assertEqual(second["candidate_ledger_new_count"], 0)
            self.assertGreaterEqual(second["candidate_ledger_existing_count"], 1)
            self.assertEqual(candidate_path.read_bytes(), before)
            summary = second["candidate_ledger_summary"]["PINNACLE_TO_DRAFTKINGS_STALE_PRICE_H2H_V1"]
            self.assertEqual(summary["candidate_n"], 1)
            self.assertEqual(summary["validation_status"], "INSUFFICIENT")
            self.assertIsNone(summary["clv"])
            self.assertIsNone(summary["flat_1u_roi"])


if __name__ == "__main__":
    unittest.main()
