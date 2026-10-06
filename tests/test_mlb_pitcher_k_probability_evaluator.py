from __future__ import annotations

import math

import pytest

from sportsedge.mlb_pitcher_k_probability_evaluator import (
    PitcherKProbabilityEvaluationError,
    evaluate_pitcher_k_candidate,
)


def _candidate(i: int):
    whiff = 0.20 + 0.002 * (i % 20)
    chase = 0.24 + 0.0015 * (i % 20)
    bf = 22.0 + (i % 5)
    return {
        "schema": "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1",
        "authority": "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED",
        "market": "PITCHER_K",
        "source_complete": True,
        "missing_components": [],
        "deployment": False,
        "model_p_eligible": False,
        "components": {
            "workload_leash": {
                "summary": {
                    "recent_mean_batters_faced": bf,
                    "recent_mean_k_per_batter_faced": 0.18 + 0.002 * (i % 15),
                    "recent_mean_pitches_per_batter_faced": 3.8 + 0.01 * (i % 6),
                }
            },
            "opponent_k": {"target_rel": 0.95 + 0.01 * (i % 10)},
            "lineup_k": {"target_deviation": 0.97 + 0.006 * (i % 10)},
            "pitcher_skill": {
                "whiff_rate": whiff,
                "chase_rate": chase,
                "pitcher_hand": "R" if i % 2 else "L",
            },
        },
    }


def _incumbent(mean: float):
    out = {}
    for k in range(20):
        line = k + 0.5
        p = 1.0 / (1.0 + math.exp((line - mean) / 1.6))
        out[f"{line:.1f}"] = p
    return out


def _rows():
    rows = []
    for season, n, offset in ((2023, 18, 0), (2024, 12, 100), (2025, 20, 200)):
        for j in range(n):
            i = offset + j
            c = _candidate(i)
            bf = int(round(c["components"]["workload_leash"]["summary"]["recent_mean_batters_faced"]))
            rate = 0.13 + 0.52 * c["components"]["pitcher_skill"]["whiff_rate"]
            k = max(0, min(bf, int(round(bf * rate))))
            rows.append(
                {
                    "season": season,
                    "pitcher_id": str(7000 + j // 2),
                    "candidate": c,
                    "realized_strikeouts": k,
                    "realized_batters_faced": bf,
                    "incumbent_p_over": _incumbent(float(k) + 0.3),
                }
            )
    return rows


def test_evaluator_selects_refits_and_remains_zero_authority():
    out = evaluate_pitcher_k_candidate(_rows())
    assert out["split"]["training_rows"] == 18
    assert out["split"]["validation_rows"] == 12
    assert out["split"]["candidate_test_rows"] == 20
    assert out["selection"]["ridge_alpha"] in {0.1, 1.0, 10.0, 100.0}
    assert out["selection"]["concentration"] in {20.0, 50.0, 100.0, 200.0, 1000000000.0}
    assert out["model_p_eligible"] is False
    assert out["deployment"] is False
    assert not any(out["authority"].values())
    assert "model_p" not in out
    assert len(out["report_sha256"]) == 64
    assert any("MIN_CANDIDATE_TEST_STARTS" in b for b in out["blockers"])


def test_missing_incumbent_threshold_fails_closed():
    rows = _rows()
    test = next(row for row in rows if row["season"] == 2025)
    del test["incumbent_p_over"]["5.5"]
    with pytest.raises(PitcherKProbabilityEvaluationError, match="incumbent probability missing"):
        evaluate_pitcher_k_candidate(rows)


def test_frozen_split_requires_all_three_seasons():
    rows = [row for row in _rows() if row["season"] != 2024]
    with pytest.raises(PitcherKProbabilityEvaluationError, match="all frozen split seasons"):
        evaluate_pitcher_k_candidate(rows)
