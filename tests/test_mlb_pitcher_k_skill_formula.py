import math

import pytest

from sportsedge.mlb_pitcher_k_skill_formula import (
    PitcherKSkillFormulaError,
    formula_features,
    research_probability_over,
)


def _candidate(lineup=True):
    components = {
        "workload_leash": {"summary": {
            "recent_mean_batters_faced": 24.0,
            "recent_mean_k_per_batter_faced": 0.25,
        }},
        "opponent_k": {
            "beta": 1.0,
            "target_rel": 1.10,
            "history_rel": [1.0, 1.0, 1.0, 1.0, 1.0],
        },
        "lineup_k": None,
        "pitcher_skill": {
            "whiff_rate": 0.30,
            "chase_rate": 0.32,
            "pitcher_hand": "R",
        },
    }
    if lineup:
        components["lineup_k"] = {
            "gamma": 0.5,
            "target_deviation": 1.21,
            "history_deviation": [1.0, 1.0, 1.0, 1.0, 1.0],
        }
    return {
        "schema": "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1",
        "authority": "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED",
        "source_complete": True,
        "missing_components": [],
        "deployment": False,
        "model_p_eligible": False,
        "components": components,
    }


def _fit():
    return {
        "schema": "MLB_PITCHER_K_SKILL_FIT_V1",
        "formula_id": "MLB_PITCHER_K_SKILL_POISSON_V1",
        "status": "FROZEN_DEVELOPMENT_FIT",
        "training_only": True,
        "forward_evaluation_rows_seen": False,
        "intercept": 0.0,
        "beta_whiff": 0.0,
        "beta_chase": 0.0,
        "whiff_mean": 0.30,
        "whiff_std": 0.05,
        "chase_mean": 0.32,
        "chase_std": 0.04,
    }


def test_formula_features_preserve_validated_fixed_offsets():
    got = formula_features(_candidate())
    assert got["opponent_factor"] == pytest.approx(1.10)
    assert got["lineup_factor"] == pytest.approx(1.10)
    assert got["base_lambda"] == pytest.approx(24.0 * 0.25 * 1.10 * 1.10)


def test_missing_lineup_is_frozen_fallback_factor_one():
    got = formula_features(_candidate(lineup=False))
    assert got["lineup_factor"] == 1.0
    assert got["base_lambda"] == pytest.approx(24.0 * 0.25 * 1.10)


def test_no_default_coefficients_or_model_p_authority():
    with pytest.raises(PitcherKSkillFormulaError, match="frozen development fit"):
        research_probability_over(_candidate(), fit={}, line=5.5)
    out = research_probability_over(_candidate(), fit=_fit(), line=5.5)
    assert 0.0 <= out["research_p_over"] <= 1.0
    assert out["model_p_eligible"] is False
    assert out["deployment"] is False
    assert "model_p" not in out


def test_zero_skill_betas_reduce_to_poisson_from_frozen_offsets():
    c = _candidate(lineup=False)
    out = research_probability_over(c, fit=_fit(), line=5.5)
    lam = 24.0 * 0.25 * 1.10
    cdf = sum(math.exp(-lam) * lam**k / math.factorial(k) for k in range(6))
    assert out["lambda"] == pytest.approx(lam)
    assert out["research_p_over"] == pytest.approx(1.0 - cdf)


def test_fit_must_predate_forward_evaluation():
    fit = _fit()
    fit["forward_evaluation_rows_seen"] = True
    with pytest.raises(PitcherKSkillFormulaError, match="predate forward evaluation"):
        research_probability_over(_candidate(), fit=fit, line=5.5)


def test_only_frozen_half_lines_are_supported():
    with pytest.raises(PitcherKSkillFormulaError, match="half-lines"):
        research_probability_over(_candidate(), fit=_fit(), line=5.0)
