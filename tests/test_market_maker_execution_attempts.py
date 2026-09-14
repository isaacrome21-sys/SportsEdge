import json
import unittest
from pathlib import Path

from scripts.evaluate_market_maker_execution_pilot import evaluate, evaluate_checkpoint
from scripts.log_market_maker_execution_attempt import ExecutionAttemptError, build_record

POLICY = json.loads(Path("config/market_maker_radar_v2.json").read_text(encoding="utf-8"))


def candidate():
    return {
        "record_type": "MARKET_MAKER_RADAR_STALE_PRICE_CANDIDATE_V1",
        "candidate_id": "cand-1",
        "source_family_id": "PINNACLE_TO_FANDUEL_STALE_PRICE_H2H_V1",
        "event_id": "event-1",
        "market": "h2h",
        "outcome": "away",
        "point": None,
        "soft_book": "fanduel",
        "candidate_created_at": "2026-09-14T12:00:00Z",
        "offered_price_american": 150,
    }


def attempt(outcome="FILLED", **overrides):
    base = {
        "candidate_id": "cand-1",
        "outcome": outcome,
        "attempted_price_american": 150,
        "filled_price_american": 150,
        "stake_requested_units": 1.0,
        "stake_accepted_units": 1.0,
        "attempted_at": "2026-09-14T12:00:20Z",
        "filled_at": "2026-09-14T12:00:22Z",
        "voided_at": None,
        "outcome_reason": None,
    }
    base.update(overrides)
    return base


def pilot_row(book="fanduel", durable=True, requested=1.0, accepted=1.0, idx=0):
    return {
        "record_type": "MARKET_MAKER_RADAR_EXECUTION_ATTEMPT_V1",
        "attempt_id": f"a-{idx:03d}",
        "attempted_at": f"2026-09-14T12:{idx:02d}:00Z",
        "soft_book": book,
        "durable_fill": durable,
        "stake_requested_units": requested,
        "stake_accepted_units": accepted,
    }


class ExecutionOutcomeTests(unittest.TestCase):
    def test_policy_freezes_all_four_execution_outcomes(self):
        self.assertEqual(
            POLICY["takeability"]["execution_outcomes"],
            ["FILLED", "FILLED_AT_CHANGED_PRICE", "REJECTED", "VOIDED_AFTER_ACCEPTANCE"],
        )
        self.assertEqual(POLICY["takeability"]["persistence_recheck_offsets_seconds"], [30, 180])
        self.assertEqual(POLICY["execution_pilot"]["status_without_attempts"], "NOT_ACCRUING_WITHOUT_EXECUTION_ATTEMPTS")

    def test_changed_price_must_be_explicit(self):
        with self.assertRaisesRegex(ExecutionAttemptError, "CHANGED_PRICE_REQUIRES_CHANGED_PRICE_OUTCOME"):
            build_record(candidate(), attempt(filled_price_american=140), POLICY)
        row = build_record(candidate(), attempt("FILLED_AT_CHANGED_PRICE", filled_price_american=140), POLICY)
        self.assertTrue(row["durable_fill"])
        self.assertEqual(row["filled_price_american"], 140)

    def test_rejection_is_not_missing_fill(self):
        row = build_record(
            candidate(),
            attempt("REJECTED", filled_price_american=None, stake_accepted_units=0, filled_at=None),
            POLICY,
        )
        self.assertFalse(row["durable_fill"])
        self.assertEqual(row["outcome"], "REJECTED")

    def test_void_after_acceptance_is_non_durable_and_preserves_accepted_stake(self):
        row = build_record(
            candidate(),
            attempt("VOIDED_AFTER_ACCEPTANCE", voided_at="2026-09-14T12:03:00Z", outcome_reason="book void"),
            POLICY,
        )
        self.assertFalse(row["durable_fill"])
        self.assertEqual(row["stake_accepted_units"], 1.0)
        self.assertEqual(row["outcome_reason"], "book void")


class PilotStopTests(unittest.TestCase):
    def test_no_attempts_is_not_accruing(self):
        report = evaluate([], POLICY)
        self.assertEqual(report["state"], "NOT_ACCRUING_WITHOUT_EXECUTION_ATTEMPTS")

    def test_ten_attempt_fill_stop_is_frozen_at_one_or_fewer_durable_fills(self):
        rule = POLICY["execution_pilot"]["stop_rules"]["at_10"]
        one = [pilot_row(durable=i == 0, idx=i) for i in range(10)]
        two = [pilot_row(durable=i < 2, idx=i) for i in range(10)]
        self.assertTrue(evaluate_checkpoint(one, 10, rule)["fill_stop_triggered"])
        self.assertFalse(evaluate_checkpoint(two, 10, rule)["fill_stop_triggered"])

    def test_twenty_attempt_fill_stop_is_frozen_at_five_or_fewer_durable_fills(self):
        rule = POLICY["execution_pilot"]["stop_rules"]["at_20"]
        five = [pilot_row(durable=i < 5, idx=i) for i in range(20)]
        six = [pilot_row(durable=i < 6, idx=i) for i in range(20)]
        self.assertTrue(evaluate_checkpoint(five, 20, rule)["fill_stop_triggered"])
        self.assertFalse(evaluate_checkpoint(six, 20, rule)["fill_stop_triggered"])

    def test_stake_acceptance_stop_is_25pct_at_10_and_40pct_at_20(self):
        r10 = POLICY["execution_pilot"]["stop_rules"]["at_10"]
        rows10 = [pilot_row(durable=True, accepted=0.2, idx=i) for i in range(10)]
        self.assertTrue(evaluate_checkpoint(rows10, 10, r10)["stake_stop_triggered"])
        r20 = POLICY["execution_pilot"]["stop_rules"]["at_20"]
        rows20 = [pilot_row(durable=True, accepted=0.39, idx=i) for i in range(20)]
        self.assertTrue(evaluate_checkpoint(rows20, 20, r20)["stake_stop_triggered"])


if __name__ == "__main__":
    unittest.main()
