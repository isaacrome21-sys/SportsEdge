from __future__ import annotations

from copy import deepcopy
import unittest

from sportsedge.sports.mlb.paired_market_evidence import (
    MLBPairedMarketEvidenceError,
    validate_paired_market_evidence,
)


H = "a" * 64
P = "b" * 64
D = "c" * 64
C = "d" * 64


def evidence():
    root = {
        "game_id": "2025-04-01-CHC-ATH",
        "market_id": "moneyline",
        "book": "DK",
        "source": "historical_archive",
        "game_start": "2025-04-01T22:05:00Z",
        "feature_source_sha256": H,
        "replay_policy_id": "MLB_REPLAY_POLICY_V1",
        "replay_policy_sha256": P,
    }
    for label, at, sha in (
        ("decision", "2025-04-01T18:00:00Z", D),
        ("close", "2025-04-01T21:55:00Z", C),
    ):
        root[label] = {
            "game_id": root["game_id"],
            "market_id": root["market_id"],
            "book": root["book"],
            "provenance": "OBSERVED_PIT",
            "reconstructed": False,
            "post_result_substitution": False,
            "imputed": False,
            "source_sha256": sha,
            "sides": [
                {"side": "home", "price": -120, "threshold": None, "observed_at": at},
                {"side": "away", "price": 110, "threshold": None, "observed_at": at},
            ],
        }
    return root


class MLBPairedMarketEvidenceTests(unittest.TestCase):
    def policy(self):
        return {"policy_id": "MLB_REPLAY_POLICY_V1", "policy_sha256": P}

    def test_valid_pair_is_ready_but_never_promotes(self):
        result = validate_paired_market_evidence(evidence(), policy_identity=self.policy())
        self.assertEqual(result["status"], "READY_FOR_REPLAY")
        self.assertFalse(result["promotion_authority"])
        self.assertFalse(result["eligible"])

    def test_one_sided_snapshot_fails_closed(self):
        row = evidence()
        row["decision"]["sides"] = row["decision"]["sides"][:1]
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "TWO_SIDES_REQUIRED"):
            validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_reconstructed_or_imputed_capture_is_forbidden(self):
        for field in ("reconstructed", "imputed", "post_result_substitution"):
            row = evidence()
            row["decision"][field] = True
            with self.assertRaises(MLBPairedMarketEvidenceError):
                validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_close_at_or_after_game_start_fails(self):
        row = evidence()
        for side in row["close"]["sides"]:
            side["observed_at"] = row["game_start"]
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "CLOSE_NOT_PREGAME"):
            validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_decision_must_precede_close(self):
        row = evidence()
        for side in row["decision"]["sides"]:
            side["observed_at"] = "2025-04-01T21:56:00Z"
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "DECISION_NOT_BEFORE_CLOSE"):
            validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_snapshot_identity_mismatch_fails(self):
        row = evidence()
        row["close"]["book"] = "OTHER"
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "SNAPSHOT_IDENTITY_MISMATCH"):
            validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_threshold_mismatch_fails(self):
        row = evidence()
        row["market_id"] = "total"
        row["decision"]["market_id"] = "total"
        row["close"]["market_id"] = "total"
        for side in row["decision"]["sides"]:
            side["threshold"] = 8.5
        for side in row["close"]["sides"]:
            side["threshold"] = 9.0
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "DECISION_CLOSE_THRESHOLD_MISMATCH"):
            validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_side_timestamp_skew_over_policy_limit_fails(self):
        row = evidence()
        row["decision"]["sides"][1]["observed_at"] = "2025-04-01T18:00:31Z"
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "SIDE_TIMESTAMP_SKEW"):
            validate_paired_market_evidence(row, policy_identity=self.policy())

    def test_policy_hash_binding_is_exact(self):
        row = evidence()
        bad = deepcopy(self.policy())
        bad["policy_sha256"] = "e" * 64
        with self.assertRaisesRegex(MLBPairedMarketEvidenceError, "POLICY_BINDING_SHA_MISMATCH"):
            validate_paired_market_evidence(row, policy_identity=bad)


if __name__ == "__main__":
    unittest.main()
