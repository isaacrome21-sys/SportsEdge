"""Synthetic timestamps/settlements, never sportsbook or backtest evidence."""
import unittest
from datetime import datetime, timezone

from sportsedge.research.pit_replay_gate import PITReplayError, partition_chronological_replay

BASE = {
    "sport": "NFL", "market": "TOTAL", "event_id": "G1", "selection_id": "S1",
    "model_version": "v1", "model_hash": "synthetic-hash", "model_frozen_at": "2026-09-01T00:00:00Z",
    "event_start_ts": "2026-10-01T18:00:00Z", "decision_ts": "2026-10-01T16:00:00Z",
    "feature_asof_ts": "2026-10-01T15:00:00Z", "settled_at": "2026-10-01T22:00:00Z",
    "source_receipt_id": "SYNTHETIC", "settlement_status": "WIN", "outcome": 1,
    "season": 2026, "model_p": 0.55,
}
HOLD = {**BASE, "event_id": "G2", "selection_id": "S2",
        "event_start_ts": "2026-10-10T18:00:00Z", "decision_ts": "2026-10-10T16:00:00Z",
        "feature_asof_ts": "2026-10-10T15:00:00Z", "settled_at": "2026-10-10T22:00:00Z"}
CUTOFF = "2026-10-05T00:00:00Z"


class PITReplayTests(unittest.TestCase):
    def partition(self, *rows):
        return partition_chronological_replay(rows or [BASE, HOLD], holdout_start=CUTOFF)

    def refuses(self, row, code):
        with self.assertRaisesRegex(PITReplayError, code):
            self.partition(BASE, row)

    def test_partition(self):
        out = self.partition()
        self.assertEqual((out["train_n"], out["holdout_n"]), (1, 1))
        self.assertFalse(out["production_eligible"])
    def test_no_holdout(self):
        with self.assertRaisesRegex(PITReplayError, "NO_CHRONOLOGICAL_HOLDOUT_ROWS"):
            self.partition(BASE)
    def test_no_training(self):
        with self.assertRaisesRegex(PITReplayError, "NO_CHRONOLOGICAL_TRAIN_ROWS"):
            self.partition(HOLD)
    def test_other_market_training_cannot_qualify_holdout(self):
        self.refuses({**HOLD, "market": "SPREAD"}, "TRAINING_GROUP_MISSING:NFL/SPREAD/v1")

    def test_other_sport_training_cannot_qualify_holdout(self):
        self.refuses({**HOLD, "sport": "NBA"}, "TRAINING_GROUP_MISSING:NBA/TOTAL/v1")

    def test_other_frozen_version_training_cannot_qualify_holdout(self):
        self.refuses({**HOLD, "model_version": "v2"}, "TRAINING_GROUP_MISSING:NFL/TOTAL/v2")

    def test_each_holdout_group_with_own_prior_rows_passes(self):
        spread_train = {**BASE, "market": "SPREAD", "selection_id": "S3"}
        spread_holdout = {**HOLD, "market": "SPREAD", "selection_id": "S4"}
        out = self.partition(BASE, spread_train, HOLD, spread_holdout)
        self.assertEqual((out["train_n"], out["holdout_n"]), (2, 2))

    def test_missing_receipt(self): self.refuses({k:v for k,v in HOLD.items() if k != "source_receipt_id"}, "source_receipt_id:MISSING")
    def test_missing_model_hash(self): self.refuses({**HOLD, "model_hash": ""}, "model_hash:NONBLANK")
    def test_poststart_decision(self): self.refuses({**HOLD, "decision_ts": HOLD["event_start_ts"]}, "FEATURE_DECISION_EVENT_SETTLEMENT_ORDER")
    def test_future_features(self): self.refuses({**HOLD, "feature_asof_ts": "2026-10-10T17:00:00Z"}, "FEATURE_DECISION_EVENT_SETTLEMENT_ORDER")
    def test_premature_settlement(self): self.refuses({**HOLD, "settled_at": "2026-10-10T17:00:00Z"}, "FEATURE_DECISION_EVENT_SETTLEMENT_ORDER")
    def test_frozen_after_decision(self): self.refuses({**HOLD, "model_frozen_at": "2026-10-10T16:01:00Z"}, "MODEL_FROZEN_AFTER_DECISION")
    def test_frozen_after_holdout(self): self.refuses({**HOLD, "model_frozen_at": "2026-10-06T00:00:00Z"}, "MODEL_NOT_FROZEN_BEFORE_HOLDOUT")
    def test_training_label_late(self):
        with self.assertRaisesRegex(PITReplayError, "TRAINING_LABEL_NOT_AVAILABLE_AT_CUTOFF"):
            self.partition({**BASE, "settled_at": "2026-10-06T00:00:00Z"}, HOLD)
    def test_duplicate(self): self.refuses(BASE, "DUPLICATE_PREDICTION_IDENTITY")
    def test_conflicting_event_clock(self): self.refuses({**HOLD, "event_id": "G1"}, "CONFLICTING_EVENT_START")
    def test_model_hash_drift(self): self.refuses({**HOLD, "model_hash": "different"}, "MODEL_VERSION_FINGERPRINT_DRIFT")
    def test_model_freeze_drift(self): self.refuses({**HOLD, "model_frozen_at": "2026-08-01T00:00:00Z"}, "MODEL_VERSION_FINGERPRINT_DRIFT")
    def test_pending(self): self.refuses({**HOLD, "settlement_status": "PENDING"}, "SETTLEMENT_UNRESOLVED")
    def test_binary_mismatch(self): self.refuses({**HOLD, "outcome": 0}, "SETTLEMENT_OUTCOME_CONFLICT")
    def test_float_outcome(self): self.refuses({**HOLD, "outcome": 1.0}, "SETTLEMENT_OUTCOME_CONFLICT")
    def test_bool_outcome(self): self.refuses({**HOLD, "outcome": True}, "SETTLEMENT_OUTCOME_CONFLICT")
    def test_push_must_be_null(self): self.refuses({**HOLD, "settlement_status": "PUSH", "outcome": 0}, "SETTLEMENT_OUTCOME_CONFLICT")
    def test_valid_push(self): self.assertEqual(self.partition(BASE, {**HOLD, "settlement_status": "PUSH", "outcome": None})["holdout_n"], 1)
    def test_naive_time(self): self.refuses({**HOLD, "decision_ts": "2026-10-10T16:00:00"}, "TIMEZONE_REQUIRED")
    def test_unsupported_sport(self): self.refuses({**HOLD, "sport": "UFC"}, "SPORT_UNSUPPORTED")
    def test_bad_identity(self): self.refuses({**HOLD, "selection_id": []}, "NONBLANK_STRING_REQUIRED")
    def test_invalid_row(self):
        with self.assertRaisesRegex(PITReplayError, "NOT_A_MAPPING"):
            self.partition(BASE, None)
    def test_cutoff_timezone(self):
        with self.assertRaisesRegex(PITReplayError, "holdout_start:TIMEZONE_REQUIRED"):
            partition_chronological_replay([BASE, HOLD], holdout_start="2026-10-05T00:00:00")
    def test_datetime_cutoff(self):
        out = partition_chronological_replay([BASE, HOLD], holdout_start=datetime(2026, 10, 5, tzinfo=timezone.utc))
        self.assertEqual(out["holdout_n"], 1)


if __name__ == "__main__": unittest.main()
