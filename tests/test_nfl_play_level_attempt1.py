import copy

import pytest

from sportsedge.sports.nfl.play_level_attempt1 import (
    ALPHA_GRID,
    FEATURE_NAMES,
    NflPlayLevelAttempt1Error,
    evaluate_2024,
    fit_attempt1,
    predict_mean,
)


def features(seed: float):
    return {
        name: seed * (index + 1) / 20.0 + ((index % 3) - 1) * 0.03
        for index, name in enumerate(FEATURE_NAMES)
    }


def row(season: int, index: int):
    hseed = (season - 2015) * 0.17 + index * 0.11
    aseed = (season - 2015) * 0.09 - index * 0.07
    home = features(hseed)
    away = features(aseed)
    diff_signal = sum(home[name] - away[name] for name in FEATURE_NAMES)
    sum_signal = sum(home[name] + away[name] for name in FEATURE_NAMES)
    noise = ((index % 5) - 2) * 0.35 + ((season + index) % 3 - 1) * 0.17
    attempt9_margin = 1.5 + ((index % 4) - 1.5) * 0.6
    attempt9_total = 43.0 + (index % 5) * 0.7
    return {
        "season": season,
        "game_id": f"{season}_{index:02d}_A_H",
        "home_features": home,
        "away_features": away,
        "attempt9_margin": attempt9_margin,
        "attempt9_total": attempt9_total,
        "actual_margin": attempt9_margin + 0.42 * diff_signal + noise,
        "actual_total": attempt9_total + 0.09 * sum_signal - 0.5 * noise,
    }


def development_rows():
    return [row(season, index) for season in range(2016, 2024) for index in range(8)]


def validation_rows():
    rows = [row(2024, index) for index in range(12)]
    for index, item in enumerate(rows):
        # Explicit home handicap convention: home cover iff
        # actual_margin + close_home_handicap > 0.
        item["close_home_handicap"] = [-3.5, -2.5, -1.5, 0.5, 1.5, 2.5][index % 6]
        item["close_total"] = [41.5, 42.5, 43.5, 44.5, 45.5, 46.5][index % 6]
    return rows


def test_fit_is_deterministic_and_uses_declared_alpha_grid():
    rows = development_rows()
    a = fit_attempt1(rows)
    b = fit_attempt1(copy.deepcopy(rows))
    assert a == b
    assert a.margin.alpha in ALPHA_GRID
    assert a.total.alpha in ALPHA_GRID
    assert a.margin.challenger_oof_sigma > 0
    assert a.margin.baseline_oof_sigma > 0
    assert a.total.challenger_oof_sigma > 0
    assert a.total.baseline_oof_sigma > 0
    assert a.authority == "RESEARCH_SHADOW_ONLY_NOT_MODEL_P"


def test_2024_row_cannot_enter_fit():
    rows = development_rows() + [row(2024, 0)]
    with pytest.raises(NflPlayLevelAttempt1Error, match="DEVELOPMENT_SEASON_LEAK"):
        fit_attempt1(rows)


def test_declared_feature_set_is_exact_and_market_fields_cannot_enter_features():
    rows = development_rows()
    bad = copy.deepcopy(rows)
    bad[0]["home_features"]["closing_spread"] = -3.5
    with pytest.raises(NflPlayLevelAttempt1Error, match="ATTEMPT1_FEATURE_SET_DRIFT"):
        fit_attempt1(bad)


def test_missing_qb_or_any_declared_feature_fails_closed():
    rows = development_rows()
    bad = copy.deepcopy(rows)
    del bad[0]["home_features"]["STARTING_QB_CPOE_SHRUNK"]
    with pytest.raises(NflPlayLevelAttempt1Error, match="ATTEMPT1_FEATURE_SET_DRIFT"):
        fit_attempt1(bad)


def test_prediction_is_attempt9_plus_learned_residual_not_a_replacement_baseline():
    rows = development_rows()
    model = fit_attempt1(rows)
    sample = row(2024, 3)
    margin = predict_mean(model, sample, "margin")
    total = predict_mean(model, sample, "total")
    assert margin != pytest.approx(sample["attempt9_margin"])
    assert total != pytest.approx(sample["attempt9_total"])


def test_evaluator_scores_only_declared_2024_half_point_rows():
    model = fit_attempt1(development_rows())
    report = evaluate_2024(model, validation_rows())
    assert report["validation_season"] == 2024
    assert report["n"] == 12
    assert set(report["gates"]) == {
        "pooled_log_loss_beats_attempt9",
        "margin_log_loss_max_regression",
        "total_log_loss_max_regression",
        "one_market_improves_log_loss_by_0_005",
        "margin_rmse_not_worse",
        "total_rmse_not_worse",
        "spread_calibration",
        "total_calibration",
    }
    assert report["diagnostic_2025_can_rescue"] is False
    assert report["authority"] == "RESEARCH_SHADOW_ONLY_NOT_MODEL_P"
    assert isinstance(report["pass"], bool)


def test_integer_validation_line_is_rejected_instead_of_using_pushless_normal():
    model = fit_attempt1(development_rows())
    rows = validation_rows()
    rows[0]["close_home_handicap"] = -3.0
    with pytest.raises(NflPlayLevelAttempt1Error, match="HALF_POINT_REQUIRED"):
        evaluate_2024(model, rows)


def test_2025_cannot_be_scored_as_attempt1_validation():
    model = fit_attempt1(development_rows())
    rows = validation_rows()
    for item in rows:
        item["season"] = 2025
    with pytest.raises(NflPlayLevelAttempt1Error, match="VALIDATION_SEASON_INVALID"):
        evaluate_2024(model, rows)


def test_evaluator_does_not_mutate_fitted_model():
    model = fit_attempt1(development_rows())
    before = model
    evaluate_2024(model, validation_rows())
    assert model == before
