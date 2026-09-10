from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from sportsedge.odds_budget import (
    OddsBudgetError,
    assert_budget_available,
    load_budget,
    record_actual_cost,
)


class OddsBudgetTests(unittest.TestCase):
    def test_positive_reserve_requires_known_provider_balance(self):
        with tempfile.TemporaryDirectory() as td:
            state = load_budget(
                Path(td) / "ledger.json",
                cap_credits=12,
                now=datetime(2026, 9, 9, tzinfo=timezone.utc),
            )
            with self.assertRaisesRegex(OddsBudgetError, "BLOCKED_PROVIDER_BALANCE_UNKNOWN"):
                assert_budget_available(state, estimated_cost=3, reserve_credits=400)

    def test_provider_reserve_blocks_before_floor_is_crossed(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.json"
            path.write_text(json.dumps({
                "date_utc": "2026-09-09",
                "consumed_credits": 0,
                "provider_credits_remaining": 453,
                "provider_credits_used": 547,
            }))
            state = load_budget(path, cap_credits=100, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
            assert_budget_available(state, estimated_cost=3, reserve_credits=450)
            with self.assertRaisesRegex(OddsBudgetError, "BLOCKED_PROVIDER_RESERVE"):
                assert_budget_available(state, estimated_cost=4, reserve_credits=450)

    def test_record_actual_cost_updates_provider_truth_atomically(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.json"
            state = load_budget(path, cap_credits=12, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
            updated = record_actual_cost(
                path,
                state=state,
                actual_cost=3,
                provider_headers={
                    "x-requests-remaining": "450",
                    "x-requests-used": "550",
                },
            )
            self.assertEqual(updated.consumed_credits, 3)
            self.assertEqual(updated.provider_credits_remaining, 450)
            raw = json.loads(path.read_text())
            self.assertEqual(raw["provider_credits_remaining"], 450)
            self.assertFalse(path.with_name("ledger.json.tmp").exists())

    def test_next_utc_day_resets_daily_spend_but_keeps_provider_balance(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.json"
            path.write_text(json.dumps({
                "date_utc": "2026-09-08",
                "consumed_credits": 9,
                "provider_credits_remaining": 453,
            }))
            state = load_budget(path, cap_credits=12, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
            self.assertEqual(state.consumed_credits, 0)
            self.assertEqual(state.provider_credits_remaining, 453)

    def test_missing_headers_decrement_last_known_provider_balance_conservatively(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.json"
            path.write_text(json.dumps({
                "date_utc": "2026-09-09",
                "consumed_credits": 0,
                "provider_credits_remaining": 453,
            }))
            state = load_budget(path, cap_credits=12, now=datetime(2026, 9, 9, tzinfo=timezone.utc))
            updated = record_actual_cost(path, state=state, actual_cost=3)
            self.assertEqual(updated.provider_credits_remaining, 450)


if __name__ == "__main__":
    unittest.main()
