import math

import numpy as np
import pytest

from sportsedge.mlb_pitcher_k_probability_model import (
    CONCENTRATION_GRID,
    HALF_LINES,
    PitcherKProbabilityModelError,
    count_distribution,
    evaluate_candidate_test,
    over_probabilities,
    predict_candidate,
    select_development_candidate,
)


def _rows(season, n, *, pitcher_offset=0):
    rows = []
    for i in range(n):
        whiff = 0.20 + 0.002 * (i % 30)
        chase = 0.25 + 0.0015 * (i % 25)
        hand = float(i % 2)
        bf = 22 + (i % 7)
        latent = -1.25 + 2.4 * (whiff - 0.23) + 0.8 * (chase - 0.27) + 0.08 * hand
        rate = 1.0 / (1.0 + math.exp(-latent))
        k = max(0, min(bf, int(round(bf * rate))))
        rows.append({
            "season": season,
            "pitcher_id": pitcher_offset + (i % 40) + 1,
            "y_k": k,
            "y_bf": bf,
            "features": {
                "recent_mean_batters_faced": float(bf) - 0.25,
                "recent_mean_k_per_batter_faced": max(0.05, rate * 0.95),
                "recent_mean_pitches_per_batter_faced": 3.7 + 0.02 * (i % 5),
                "opponent_target_rel": 0.9 + 0.01 * (i % 20),
                "lineup_target_deviation_or_1": 0.95 + 0.01 * (i % 10),
                "whiff_rate": whiff,
                "chase_rate": chase,
                "pitcher_hand_R": hand,
            },
        })
    return rows


def test_count_distribution_conserves_mass_and_over_is_monotone():
    for concentration in (20.0, 1_000_000_000.0):
        mass = count_distribution(27, 0.24, concentration)
        assert mass.sum() == pytest.approx(1.0, abs=1e-12)
        over = over_probabilities(27, 0.24, concentration)
        assert len(over) == len(HALF_LINES)
        assert np.all(np.diff(over) <= 1e-12)


def test_selection_is_deterministic_and_refits_only_2023_2024():
    train = _rows(2023, 120)
    valid = _rows(2024, 100, pitcher_offset=100)
    a = select_development_candidate(train, valid)
    b = select_development_candidate(train, valid)
    assert a["selected_alpha"] == b["selected_alpha"]
    assert a["selected_concentration"] == b["selected_concentration"]
    assert a["selection_validation_mean_rps"] == pytest.approx(b["selection_validation_mean_rps"])
    assert a["training_seasons"] == [2023]
    assert a["validation_seasons"] == [2024]
    assert a["refit_seasons"] == [2023, 2024]
    assert a["candidate_test_rows_seen"] is False
    assert a["sportsbook_prices_used"] is False
    assert a["model_p_eligible"] is False


def test_selection_rejects_wrong_season_boundary():
    with pytest.raises(PitcherKProbabilityModelError, match="2023 training / 2024 validation"):
        select_development_candidate(_rows(2024, 20), _rows(2025, 20))


def test_predict_requires_frozen_uncontaminated_artifact():
    artifact = select_development_candidate(_rows(2023, 80), _rows(2024, 80))
    rows = _rows(2025, 5)
    pred = predict_candidate(rows, artifact)
    assert len(pred) == 5
    assert all(len(p) == 20 for p in pred)
    contaminated = dict(artifact)
    contaminated["candidate_test_rows_seen"] = True
    with pytest.raises(PitcherKProbabilityModelError, match="contaminated"):
        predict_candidate(rows, contaminated)


def test_2025_evaluation_is_zero_authority_and_uses_frozen_incumbent_vector():
    artifact = select_development_candidate(_rows(2023, 100), _rows(2024, 100))
    test = _rows(2025, 500, pitcher_offset=500)
    candidate = predict_candidate(test, artifact)
    for row, pred in zip(test, candidate):
        # Equal incumbent forces a non-pass on the strict RPS superiority rule.
        row["incumbent_p_over"] = pred.tolist()
    report = evaluate_candidate_test(test, artifact)
    assert report["starts"] == 500
    assert report["rps_difference_bootstrap"]["diff"] == pytest.approx(0.0)
    assert report["pass_rules"]["rps_ci_high_lt_0"] is False
    assert report["development_pass"] is False
    assert report["model_p_eligible"] is False
    assert report["deployment"] is False
    assert report["promotion_authority"] is False


def test_evaluation_refuses_underpowered_or_non_2025_readout():
    artifact = select_development_candidate(_rows(2023, 80), _rows(2024, 80))
    short = _rows(2025, 30)
    with pytest.raises(PitcherKProbabilityModelError, match="at least 500"):
        evaluate_candidate_test(short, artifact)
    wrong = _rows(2024, 500)
    with pytest.raises(PitcherKProbabilityModelError, match="2025 candidate-test"):
        evaluate_candidate_test(wrong, artifact)
