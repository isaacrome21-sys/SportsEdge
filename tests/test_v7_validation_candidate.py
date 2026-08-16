import unittest

from sportsedge.v7_candidate import V7CandidateError, build_candidate_artifact, load_candidate, score_candidate
from sportsedge.v7_validation import (
    V7ValidationError, compare_candidate_to_baseline, make_expanding_splits,
    score_fold, summarize_walk_forward, verify_untouched_holdout,
)


class V7ValidationCandidateTests(unittest.TestCase):
    def test_expanding_splits_are_strictly_chronological(self):
        splits = make_expanding_splits(
            first_train_end="2026-05-31",
            validation_starts=["2026-06-01", "2026-07-01"],
            validation_ends=["2026-06-30", "2026-07-31"],
        )
        self.assertEqual(splits[1].train_end, "2026-06-30")
        with self.assertRaises(V7ValidationError):
            make_expanding_splits(
                first_train_end="2026-05-31",
                validation_starts=["2026-05-31"],
                validation_ends=["2026-06-30"],
            )

    def test_holdout_contamination_fails_closed(self):
        verify_untouched_holdout([{"fit_max_date": "2026-07-31"}], holdout_start="2026-08-01", holdout_end="2026-08-15")
        with self.assertRaises(V7ValidationError):
            verify_untouched_holdout([{"fit_max_date": "2026-08-01"}], holdout_start="2026-08-01", holdout_end="2026-08-15")

    def test_walk_forward_metrics_are_paired_and_hashed(self):
        candidate = score_fold(name="candidate", probabilities=[0.2, 0.8, 0.3, 0.7], outcomes=[0, 1, 0, 1])
        baseline = score_fold(name="baseline", probabilities=[0.3, 0.7, 0.4, 0.6], outcomes=[0, 1, 0, 1])
        comparison = compare_candidate_to_baseline(candidate=candidate, baseline=baseline)
        self.assertLess(comparison["brier_delta"], 0)
        summary = summarize_walk_forward([candidate])
        self.assertEqual(len(summary["summary_sha256"]), 64)

    def test_candidate_hash_and_feature_contract_are_enforced(self):
        artifact = build_candidate_artifact(
            model_name="test_v7",
            feature_contract_sha256="feature-hash",
            intercept=-0.2,
            coefficients={"starter.days_rest": 0.1, "statcast.xwoba_30d": 1.5},
        )
        candidate = load_candidate(artifact)
        features = {
            "feature_contract_sha256": "feature-hash",
            "starter": {"days_rest": 5.0},
            "statcast": {"xwoba_30d": 0.35},
        }
        p = score_candidate(candidate, features)
        self.assertGreater(p, 0)
        self.assertLess(p, 1)
        with self.assertRaises(V7CandidateError):
            score_candidate(candidate, {**features, "feature_contract_sha256": "changed"})
        tampered = dict(artifact)
        tampered["intercept"] = 9.0
        with self.assertRaises(V7CandidateError):
            load_candidate(tampered)

    def test_candidate_rejects_sportsbook_fields(self):
        artifact = build_candidate_artifact(
            model_name="test_v7", feature_contract_sha256="feature-hash",
            intercept=0.0, coefficients={"x": 1.0},
        )
        candidate = load_candidate(artifact)
        with self.assertRaises(Exception):
            score_candidate(candidate, {
                "feature_contract_sha256": "feature-hash", "x": 1.0,
                "nested": {"sportsbook": "book"},
            })


if __name__ == "__main__":
    unittest.main()
