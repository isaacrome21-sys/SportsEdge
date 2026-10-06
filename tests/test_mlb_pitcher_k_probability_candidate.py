from __future__ import annotations

import pytest

from sportsedge.mlb_pitcher_k_probability_candidate import (
    AUTHORITY,
    PitcherKProbabilityCandidateError,
    count_mass,
    feature_vector,
    fit_rate_model,
    predict_k_rate,
    price_threshold,
    rps_for_realized_count,
    select_hyperparameters,
)


def _candidate(*, whiff=0.25, chase=0.27, kbf=0.22, bf=24.0, hand="R"):
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
                    "recent_mean_k_per_batter_faced": kbf,
                    "recent_mean_pitches_per_batter_faced": 3.9,
                }
            },
            "opponent_k": {"target_rel": 1.05},
            "lineup_k": {"target_deviation": 1.03},
            "pitcher_skill": {
                "whiff_rate": whiff,
                "chase_rate": chase,
                "pitcher_hand": hand,
            },
        },
    }


def _rows(n=20, *, shift=0.0):
    rows = []
    for i in range(n):
        whiff = 0.18 + 0.006 * i + shift
        chase = 0.22 + 0.003 * i
        bf = 22 + (i % 5)
        k = max(1, min(bf - 1, round(bf * (0.12 + 0.55 * whiff))))
        rows.append(
            {
                "pitcher_id": 1000 + i // 2,
                "candidate": _candidate(
                    whiff=whiff,
                    chase=chase,
                    kbf=0.17 + 0.004 * i,
                    bf=float(bf),
                    hand="R" if i % 2 else "L",
                ),
                "realized_strikeouts": int(k),
                "realized_batters_faced": int(bf),
            }
        )
    return rows


def test_feature_vector_is_exact_preregistered_shape():
    values = feature_vector(_candidate())
    assert len(values) == 8
    assert values[0] == 24.0
    assert values[5] == 0.25
    assert values[7] == 1.0


def test_rate_fit_learns_monotone_skill_signal_on_synthetic_rows():
    fit = fit_rate_model(_rows(), ridge_alpha=1.0)
    low = predict_k_rate(fit, _candidate(whiff=0.19, chase=0.23, kbf=0.18))
    high = predict_k_rate(fit, _candidate(whiff=0.30, chase=0.30, kbf=0.27))
    assert 0 < low < high < 1
    assert fit.training_rows == 20
    assert len(fit.fit_sha256) == 64


def test_beta_binomial_mass_and_threshold_price_conserve_probability():
    mass = count_mass(n_trials=25, k_rate=0.25, concentration=50.0)
    assert len(mass) == 26
    assert sum(mass) == pytest.approx(1.0, abs=1e-12)
    fit = fit_rate_model(_rows(), ridge_alpha=1.0)
    half = price_threshold(_candidate(), fit, concentration=50.0, line=5.5)
    assert half["candidate_p_push"] == 0.0
    assert half["candidate_p_over"] + half["candidate_p_under"] == pytest.approx(1.0)
    integer = price_threshold(_candidate(), fit, concentration=50.0, line=5.0)
    assert integer["candidate_p_push"] > 0
    assert (
        integer["candidate_p_over"]
        + integer["candidate_p_under"]
        + integer["candidate_p_push"]
    ) == pytest.approx(1.0)


def test_candidate_readout_cannot_be_mistaken_for_production_model_p():
    fit = fit_rate_model(_rows(), ridge_alpha=1.0)
    out = price_threshold(_candidate(), fit, concentration=100.0, line=5.5)
    assert "model_p" not in out
    assert out["model_p_eligible"] is False
    assert out["deployment"] is False
    assert out["authority"] == AUTHORITY


def test_hyperparameter_selection_stays_inside_frozen_grid():
    selected = select_hyperparameters(_rows(16), _rows(8, shift=0.005))
    assert selected["ridge_alpha"] in {0.1, 1.0, 10.0, 100.0}
    assert selected["concentration"] in {20.0, 50.0, 100.0, 200.0, 1000000000.0}
    assert len(selected["grid_scores"]) == 20


def test_rps_is_finite_and_bounded():
    fit = fit_rate_model(_rows(), ridge_alpha=10.0)
    score = rps_for_realized_count(
        _candidate(), fit, concentration=100.0, realized_strikeouts=6
    )
    assert 0.0 <= score <= 1.0


def test_incomplete_or_deployable_candidate_fails_closed():
    bad = _candidate()
    bad["source_complete"] = False
    with pytest.raises(PitcherKProbabilityCandidateError, match="incomplete"):
        feature_vector(bad)
    bad = _candidate()
    bad["model_p_eligible"] = True
    with pytest.raises(PitcherKProbabilityCandidateError, match="deployable"):
        feature_vector(bad)


def test_rate_features_reject_closed_interval_boundaries():
    for field in ("whiff_rate", "chase_rate"):
        for value in (0.0, 1.0):
            bad = _candidate()
            bad["components"]["pitcher_skill"][field] = value
            with pytest.raises(PitcherKProbabilityCandidateError):
                feature_vector(bad)

    for value in (0.0, 1.0):
        bad = _candidate(kbf=value)
        with pytest.raises(PitcherKProbabilityCandidateError):
            feature_vector(bad)
