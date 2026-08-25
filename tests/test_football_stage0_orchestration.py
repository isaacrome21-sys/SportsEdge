import unittest
from datetime import datetime, timezone, timedelta

from sportsedge.core.run_state import (
    SlotState,
    classify_acquisition,
    summarize_run,
    validate_slot_state,
    evaluate_external_heartbeat,
)


class FootballStageZeroOrchestrationTests(unittest.TestCase):
    def test_acquisition_distinguishes_missing_not_offered_and_unsupported(self):
        self.assertEqual(
            classify_acquisition(provider_supported=True, request_succeeded=False, offer_found=False),
            "ACQUISITION_MISSING",
        )
        self.assertEqual(
            classify_acquisition(provider_supported=True, request_succeeded=True, offer_found=False),
            "NOT_OFFERED",
        )
        self.assertEqual(
            classify_acquisition(provider_supported=False, request_succeeded=True, offer_found=False),
            "PROVIDER_UNSUPPORTED",
        )
        self.assertEqual(
            classify_acquisition(provider_supported=True, request_succeeded=True, offer_found=True),
            "OFFERED",
        )

    def test_pass_only_exists_for_offered_and_priced_slot(self):
        validate_slot_state(SlotState("g1", "spread", "OFFERED", "PRICED", "PASS"))
        with self.assertRaisesRegex(ValueError, "DECISION_REQUIRES_PRICED_OFFER"):
            validate_slot_state(SlotState("g1", "spread", "NOT_OFFERED", "INPUT_MISSING", "PASS"))
        with self.assertRaisesRegex(ValueError, "DECISION_REQUIRES_PRICED_OFFER"):
            validate_slot_state(SlotState("g1", "spread", "OFFERED", "NO_ENGINE", "PASS"))

    def test_all_blocked_run_never_reports_ready(self):
        slots = [
            SlotState("g1", "spread", "OFFERED", "ENGINE_BLOCKED", None),
            SlotState("g1", "total", "ACQUISITION_MISSING", "INPUT_MISSING", None),
        ]
        summary = summarize_run(slots)
        self.assertEqual(summary.run_status, "BLOCKED")
        self.assertEqual(summary.card_status, "NO_BETS")
        self.assertEqual(summary.priced_slots, 0)

    def test_partial_pricing_with_missing_inputs_is_degraded_not_ready(self):
        slots = [
            SlotState("g1", "spread", "OFFERED", "PRICED", "PASS"),
            SlotState("g1", "total", "ACQUISITION_MISSING", "INPUT_MISSING", None),
        ]
        summary = summarize_run(slots)
        self.assertEqual(summary.run_status, "DEGRADED")
        self.assertEqual(summary.card_status, "NO_BETS")
        self.assertEqual(summary.priced_slots, 1)

    def test_ready_run_can_legitimately_have_no_bets(self):
        slots = [
            SlotState("g1", "spread", "OFFERED", "PRICED", "PASS"),
            SlotState("g1", "total", "NOT_OFFERED", "INPUT_MISSING", None),
        ]
        summary = summarize_run(slots)
        self.assertEqual(summary.run_status, "READY")
        self.assertEqual(summary.card_status, "NO_BETS")

    def test_bet_sets_card_status_bets_found(self):
        slots = [SlotState("g1", "spread", "OFFERED", "PRICED", "BET")]
        summary = summarize_run(slots)
        self.assertEqual(summary.run_status, "READY")
        self.assertEqual(summary.card_status, "BETS_FOUND")

    def test_external_heartbeat_is_distinct_from_actions_execution(self):
        now = datetime(2026, 8, 24, 22, 0, tzinfo=timezone.utc)
        fresh = evaluate_external_heartbeat(
            observer="CHATGPT_EXTERNAL_CHECK",
            observed_at=now - timedelta(minutes=10),
            now=now,
            max_age=timedelta(minutes=30),
        )
        self.assertTrue(fresh.fresh)
        self.assertEqual(fresh.status, "EXTERNAL_HEARTBEAT_FRESH")
        stale = evaluate_external_heartbeat(
            observer="CHATGPT_EXTERNAL_CHECK",
            observed_at=now - timedelta(hours=2),
            now=now,
            max_age=timedelta(minutes=30),
        )
        self.assertFalse(stale.fresh)
        self.assertEqual(stale.status, "EXTERNAL_HEARTBEAT_STALE")
        with self.assertRaisesRegex(ValueError, "EXTERNAL_OBSERVER_REQUIRED"):
            evaluate_external_heartbeat(
                observer="github-actions",
                observed_at=now,
                now=now,
                max_age=timedelta(minutes=30),
            )


if __name__ == "__main__":
    unittest.main()
