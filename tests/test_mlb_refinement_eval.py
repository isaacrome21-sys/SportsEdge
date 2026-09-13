import math
import pytest

from sportsedge.mlb_refinement_eval import (
    MLBRefinementEvalError,
    compare_paired_rows,
    decide_ablation,
    evaluate_probabilities,
)


def _row(game, p, outcome):
    return {
        "game_id": str(game),
        "market": "NRFI",
        "entity_id": str(game),
        "side": "YES",
        "line": 0.5,
        "as_of_utc": "2026-08-10T12:00:00+00:00",
        "model_p": p,
        "outcome": outcome,
    }


def test_evaluate_probabilities_scores_and_buckets():
    report = evaluate_probabilities([0.1, 0.9], [0, 1])
    assert report.n == 2
    assert report.brier == pytest.approx(0.01)
    assert report.logloss == pytest.approx(-math.log(0.9))
    assert report.calibration_mae == pytest.approx(0.1)
    assert sum(b.n for b in report.buckets) == 2


def test_compare_paired_rows_detects_improvement():
    baseline = [_row(1, 0.6, 0), _row(2, 0.6, 1), _row(3, 0.6, 0), _row(4, 0.6, 1)]
    candidate = [_row(1, 0.45, 0), _row(2, 0.55, 1), _row(3, 0.45, 0), _row(4, 0.55, 1)]
    comparison = compare_paired_rows(baseline, candidate)
    assert comparison.n == 4
    assert comparison.brier_delta < 0
    assert comparison.logloss_delta < 0


def test_compare_paired_rows_fails_on_identity_mismatch():
    with pytest.raises(MLBRefinementEvalError, match="paired identities differ"):
        compare_paired_rows([_row(1, 0.5, 0)], [_row(2, 0.5, 0)])


def test_compare_paired_rows_fails_on_outcome_mismatch():
    with pytest.raises(MLBRefinementEvalError, match="paired outcome mismatch"):
        compare_paired_rows([_row(1, 0.5, 0)], [_row(1, 0.5, 1)])


def test_ablation_requires_minimum_evidence():
    current = [_row(1, 0.7, 1), _row(2, 0.3, 0)]
    without = [_row(1, 0.6, 1), _row(2, 0.4, 0)]
    comparison = compare_paired_rows(current, without)
    decision = decide_ablation(feature="weather", comparison_without_feature=comparison, minimum_n=200)
    assert decision.action == "INSUFFICIENT_EVIDENCE"


def test_ablation_remove_when_feature_hurts_both_scores():
    current = []
    without = []
    for i in range(200):
        outcome = i % 2
        current.append(_row(i, 0.65 if outcome else 0.35, outcome))
        without.append(_row(i, 0.75 if outcome else 0.25, outcome))
    comparison = compare_paired_rows(current, without)
    decision = decide_ablation(feature="noisy_external_signal", comparison_without_feature=comparison, minimum_n=200)
    assert decision.action == "REMOVE"


def test_ablation_keep_when_feature_helps_both_scores():
    current = []
    without = []
    for i in range(200):
        outcome = i % 2
        current.append(_row(i, 0.75 if outcome else 0.25, outcome))
        without.append(_row(i, 0.65 if outcome else 0.35, outcome))
    comparison = compare_paired_rows(current, without)
    decision = decide_ablation(feature="top_order_hazard", comparison_without_feature=comparison, minimum_n=200)
    assert decision.action == "KEEP"
