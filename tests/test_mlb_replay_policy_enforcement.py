from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest

from sportsedge.sports.mlb.replay_policy import (
    MLBReplayPolicyError,
    enforce_replay_policy_binding,
    load_replay_policy,
    validate_replay_policy,
)


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "config" / "mlb_replay_policy_v1.json"


class MLBReplayPolicyEnforcementTests(unittest.TestCase):
    def test_frozen_policy_validates_and_hashes_exact_bytes(self):
        identity = load_replay_policy(POLICY)
        self.assertEqual(identity["policy_id"], "MLB_REPLAY_POLICY_V1")
        self.assertEqual(identity["status"], "FROZEN_PRE_REPLAY")
        self.assertEqual(identity["replay_end"], "2026-08-31")
        self.assertEqual(identity["untouched_holdout_start"], "2026-09-01")
        self.assertEqual(identity["untouched_holdout_end"], "2026-09-27")
        self.assertEqual(len(identity["policy_sha256"]), 64)

    def test_fold_gap_or_overlap_is_rejected(self):
        payload = json.loads(POLICY.read_text(encoding="utf-8"))
        broken = deepcopy(payload)
        broken["walk_forward"]["folds"][1]["validation_start"] = "2026-05-02"
        raw = (json.dumps(broken, sort_keys=True) + "\n").encode()
        with self.assertRaisesRegex(MLBReplayPolicyError, "FOLD_GAP_OR_OVERLAP"):
            validate_replay_policy(broken, raw_bytes=raw)

    def test_unbound_historical_pass_fails_closed(self):
        identity = load_replay_policy(POLICY)
        markets = {
            "MONEYLINE": {
                "historical_point_in_time": {"status": "PASS", "sample_size": 999},
                "untouched_holdout": {"status": "PENDING"},
            }
        }
        out = enforce_replay_policy_binding(markets, policy_identity=identity, as_of_date=date(2026, 10, 1))
        gate = out["MONEYLINE"]["historical_point_in_time"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(gate["reason"], "MLB_REPLAY_POLICY_BINDING_MISSING_OR_MISMATCH")

    def test_exact_bound_historical_pass_is_preserved(self):
        identity = load_replay_policy(POLICY)
        markets = {
            "MONEYLINE": {
                "historical_point_in_time": {
                    "status": "PASS",
                    "replay_policy_id": identity["policy_id"],
                    "replay_policy_sha256": identity["policy_sha256"],
                },
                "untouched_holdout": {"status": "PENDING"},
            }
        }
        out = enforce_replay_policy_binding(markets, policy_identity=identity, as_of_date=date(2026, 10, 1))
        self.assertEqual(out["MONEYLINE"]["historical_point_in_time"]["status"], "PASS")

    def test_untouched_holdout_cannot_pass_before_window_completes(self):
        identity = load_replay_policy(POLICY)
        markets = {
            "MONEYLINE": {
                "historical_point_in_time": {"status": "PENDING"},
                "untouched_holdout": {
                    "status": "PASS",
                    "replay_policy_id": identity["policy_id"],
                    "replay_policy_sha256": identity["policy_sha256"],
                },
            }
        }
        out = enforce_replay_policy_binding(markets, policy_identity=identity, as_of_date=date(2026, 9, 15))
        gate = out["MONEYLINE"]["untouched_holdout"]
        self.assertEqual(gate["status"], "FAIL")
        self.assertEqual(gate["reason"], "MLB_REPLAY_UNTOUCHED_HOLDOUT_WINDOW_INCOMPLETE")

    def test_exact_bound_holdout_pass_is_preserved_after_window(self):
        identity = load_replay_policy(POLICY)
        markets = {
            "MONEYLINE": {
                "historical_point_in_time": {"status": "PENDING"},
                "untouched_holdout": {
                    "status": "PASS",
                    "replay_policy_id": identity["policy_id"],
                    "replay_policy_sha256": identity["policy_sha256"],
                },
            }
        }
        out = enforce_replay_policy_binding(markets, policy_identity=identity, as_of_date=date(2026, 9, 28))
        self.assertEqual(out["MONEYLINE"]["untouched_holdout"]["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
