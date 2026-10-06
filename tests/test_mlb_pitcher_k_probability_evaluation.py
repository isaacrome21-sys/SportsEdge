from __future__ import annotations

import copy

import numpy as np
import pytest

from sportsedge.mlb_pitcher_k_probability_candidate import (
    HALF_LINES,
    price_threshold,
)
from sportsedge.mlb_pitcher_k_probability_evaluation import (
    PitcherKProbabilityEvaluationError,
    build_development_fit,
    candidate_over_vector,
    evaluate_candidate_test,
)


AUTHORITY = "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED"


def _candidate(i: int):
    bf = 22.0 + (i % 6)
    whiff = 0.18 + 0.004 * (i % 25)
    chase = 0.22 + 0.003 * (i % 20)
    return {
        "schema": "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1",
        "authority": AUTHORITY,
        "market": "PITCHER_K",
        "source_complete": True,
        "missing_components": [],
        "deployment": False,
        "model_p_eligible": False,
        "components": {
            "workload_leash": {
                "summary": {
                    "recent_mean_batters_faced": bf,
                    "recent_mean_k_per_batter_faced": 0.16 + 0.003 * (i % 20),
                    "recent_mean_pitches_per_batter_faced": 3.7 + 0.03 * (i % 5),
                }
            },
            "opponent_k": {"target_rel": 0.92 + 0.01 * (i % 17)},
            "lineup_k": None if i % 3 == 0 else {"target_deviation": 0.95 + 0.01 * (i % 11)},
            "pitcher_skill": {
                "whiff_rate": whiff,
                "chase_rate": chase,
                "pitcher_hand": "R" if i % 2 else "L",
            },
        },
    }


def _rows(season: int, n: int, offset: int = 0):
    rows = []
    for j in range(n):
        i = j + offset
        candidate = _candidate(i)
        bf = 22 + (i % 6)
        skill = candidate["components"]["pitcher_skill"]
        rate = 0.10 + 0.45 * skill["whiff_rate"] + 0.08 * skill["chase_rate"]
        k = max(0, min(bf, int(round(bf * rate))))
        rows.append({
            "season": season,
            "pitcher_id": 1000 + (j % 50),
            "candidate": candidate,
            "realized_strikeouts": k,
            "realized_batters_faced": bf,
        })
    return rows


def test_development_fit_locks_2023_2024_and_zero_authority():
    artifact = build_development_fit(_rows(2023, 40), _rows(2024, 30, 100))
    assert artifact["training_seasons"] == [2023]
    assert artifact["validation_seasons"] == [2024]
    assert artifact["refit_seasons"] == [2023, 2024]
    assert artifact["candidate_test_rows_seen"] is False
    assert artifact["sportsbook_prices_used"] is False
    assert artifact["model_p_eligible"] is False
    assert artifact["deployment"] is False
    assert len(artifact["development_fit_sha256"]) == 64


def test_development_fit_rejects_season_leakage():
    with pytest.raises(PitcherKProbabilityEvaluationError, match="frozen season 2023"):
        build_development_fit(_rows(2024, 20), _rows(2024, 20))


def test_artifact_digest_and_candidate_test_contamination_fail_closed():
    artifact = build_development_fit(_rows(2023, 30), _rows(2024, 20, 100))
    row = _rows(2025, 1, 200)[0]
    assert len(candidate_over_vector(row, artifact)) == len(HALF_LINES)

    bad = copy.deepcopy(artifact)
    bad["selected_ridge_alpha"] = 999.0
    with pytest.raises(PitcherKProbabilityEvaluationError, match="digest"):
        candidate_over_vector(row, bad)

    bad = copy.deepcopy(artifact)
    bad["candidate_test_rows_seen"] = True
    with pytest.raises(PitcherKProbabilityEvaluationError, match="saw candidate-test"):
        candidate_over_vector(row, bad)


def test_one_look_evaluator_enforces_500_2025_rows_and_zero_authority():
    artifact = build_development_fit(_rows(2023, 40), _rows(2024, 30, 100))
    test = _rows(2025, 500, 200)
    # Use the exact candidate vector as incumbent: strict-superiority rule must fail.
    for row in test:
        row["incumbent_p_over"] = candidate_over_vector(row, artifact).tolist()
    report = evaluate_candidate_test(test, artifact)
    assert report["candidate_test_rows"] == 500
    assert report["candidate_test_seasons"] == [2025]
    assert report["rps_difference_bootstrap"]["diff"] == pytest.approx(0.0)
    assert report["pass_rules"]["candidate_rps_minus_incumbent_ci_high_lt_0"] is False
    assert report["development_pass"] is False
    assert report["candidate_test_is_broader_promotion_evidence"] is False
    assert report["model_p_eligible"] is False
    assert report["deployment"] is False
    assert report["promotion_authority"] is False
    assert len(report["readout_sha256"]) == 64


def test_one_look_evaluator_rejects_underpowered_or_wrong_season():
    artifact = build_development_fit(_rows(2023, 30), _rows(2024, 20, 100))
    short = _rows(2025, 20, 200)
    with pytest.raises(PitcherKProbabilityEvaluationError, match="at least 500"):
        evaluate_candidate_test(short, artifact)
    wrong = _rows(2024, 500, 200)
    with pytest.raises(PitcherKProbabilityEvaluationError, match="frozen season 2025"):
        evaluate_candidate_test(wrong, artifact)
