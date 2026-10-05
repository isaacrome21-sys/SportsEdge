from __future__ import annotations

import numpy as np
import pytest

from sportsedge.sports.nfl.score_counts_g1 import (
    FEATURE_NAMES,
    FG_ATTEMPT2_ALPHA_GRID,
    FG_ATTEMPT2_FEATURE_NAMES,
    ROOT_SEED_UINT64,
    ScoreCountsError,
    child_seed,
    empirical_bayes_rate,
    fit_core,
    fit_poisson_ridge,
    market_probability,
    predict_mean,
    simulate_game,
)


def row(season: int, strength: float, *, home: bool, td: int, fg: int):
    values = {
        "season": season,
        "offense_touchdowns": td,
        "made_field_goals": fg,
    }
    for idx, name in enumerate(FEATURE_NAMES):
        if name == "home_indicator":
            values[name] = 1.0 if home else 0.0
        elif "turnover" in name or "sack_rate" in name or "success_rate" in name:
            values[name] = 0.05 + 0.01 * strength + idx * 1e-4
        elif "cpoe" in name:
            values[name] = strength * 0.5
        else:
            values[name] = 1.0 + strength * (0.2 + idx * 0.01)
    return values


def training_rows():
    out = []
    for season in (2018, 2019, 2020, 2021):
        for i in range(10):
            strength = -1.0 + 2.0 * i / 9.0 + 0.05 * (season - 2018)
            td = max(0, int(round(2.2 + 0.9 * strength + (i % 2) * 0.2)))
            fg = max(0, int(round(1.7 + 0.4 * strength + (i % 3) * 0.15)))
            out.append(row(season, strength, home=(i % 2 == 0), td=td, fg=fg))
    return out


def fit():
    return fit_core(
        training_rows(),
        shared_sigma=0.10,
        def_st_td_rate=0.08,
        safety_rate=0.015,
        conversion_probabilities=(0.92, 0.05, 0.03),
        source_manifest_sha256="a" * 64,
        code_identity="synthetic-core-test",
    )


def test_child_seed_is_deterministic_and_game_specific():
    assert child_seed("G1") == child_seed("G1")
    assert child_seed("G1") != child_seed("G2")
    assert ROOT_SEED_UINT64 == 16316594915016045197


def test_poisson_ridge_fit_is_deterministic_and_strength_sensitive():
    rows = training_rows()
    a = fit_poisson_ridge(rows, target="offense_touchdowns", alpha=1.0)
    b = fit_poisson_ridge(rows, target="offense_touchdowns", alpha=1.0)
    assert a == b
    weak = row(2022, -1.0, home=False, td=0, fg=0)
    strong = row(2022, 1.0, home=True, td=0, fg=0)
    assert predict_mean(a, strong) > predict_mean(a, weak)


def test_empirical_bayes_rate_shrinks_toward_league():
    raw = 5 / 10
    league = 0.10
    got = empirical_bayes_rate(events=5, exposure=10, league_rate=league, prior_exposure=25)
    assert league < got < raw


def test_core_fit_selects_frozen_grid_and_keeps_zero_authority():
    model = fit()
    assert model.td_model.alpha in {0.1, 1.0, 10.0, 100.0}
    assert model.fg_model.alpha in {0.1, 1.0, 10.0, 100.0}
    assert model.shared_sigma == 0.10


def test_simulation_is_deterministic_for_same_seed_and_joint():
    model = fit()
    home = row(2022, 0.8, home=True, td=0, fg=0)
    away = row(2022, -0.3, home=False, td=0, fg=0)
    a = simulate_game(model, game_id="G", home_row=home, away_row=away, paths=10000, seed=7)
    b = simulate_game(model, game_id="G", home_row=home, away_row=away, paths=10000, seed=7)
    assert np.array_equal(a["home_score"], b["home_score"])
    assert np.array_equal(a["away_score"], b["away_score"])
    assert np.array_equal(a["margin"], a["home_score"] - a["away_score"])
    assert np.array_equal(a["total"], a["home_score"] + a["away_score"])
    assert a["authority"]["creates_model_p"] is False
    assert a["authority"]["pricing"] is False


def test_smoke_path_count_is_explicitly_not_scored():
    model = fit()
    x = row(2022, 0.2, home=True, td=0, fg=0)
    y = row(2022, 0.1, home=False, td=0, fg=0)
    out = simulate_game(model, game_id="SMOKE", home_row=x, away_row=y, paths=500, seed=3)
    assert out["status"] == "SMOKE_ONLY"


def test_all_market_probabilities_come_from_same_path_arrays_and_keep_push():
    sim = {
        "home_score": np.asarray([24, 21, 20, 17]),
        "away_score": np.asarray([20, 21, 24, 17]),
        "margin": np.asarray([4, 0, -4, 0]),
        "total": np.asarray([44, 42, 44, 34]),
    }
    ml = market_probability(sim, market="moneyline", selection="home")
    assert ml == pytest.approx({"win_p": 0.25, "push_p": 0.50, "loss_p": 0.25})
    spread = market_probability(sim, market="spread", selection="home", line=4.0)
    assert spread["push_p"] == pytest.approx(0.25)
    total = market_probability(sim, market="total", selection="over", line=44.0)
    assert total["push_p"] == pytest.approx(0.50)
    tt = market_probability(sim, market="team_total", selection="home_over", line=21.0)
    assert tt["push_p"] == pytest.approx(0.25)


def test_fit_rejects_invalid_source_identity_and_sigma():
    rows = training_rows()
    with pytest.raises(ScoreCountsError, match="SHARED_SIGMA"):
        fit_core(
            rows,
            shared_sigma=0.15,
            def_st_td_rate=0.08,
            safety_rate=0.015,
            conversion_probabilities=(0.92, 0.05, 0.03),
            source_manifest_sha256="a" * 64,
            code_identity="x",
        )
    with pytest.raises(ScoreCountsError, match="SOURCE_MANIFEST"):
        fit_core(
            rows,
            shared_sigma=0.10,
            def_st_td_rate=0.08,
            safety_rate=0.015,
            conversion_probabilities=(0.92, 0.05, 0.03),
            source_manifest_sha256="short",
            code_identity="x",
        )


def test_team_specific_rare_score_and_conversion_overrides_are_used():
    model = fit()
    home = row(2022, 0.4, home=True, td=0, fg=0)
    away = row(2022, 0.4, home=False, td=0, fg=0)
    home.update({
        "def_st_td_rate": 0.0,
        "safety_rate": 0.0,
        "conversion_pat_p": 1.0,
        "conversion_two_p": 0.0,
        "conversion_no_p": 0.0,
    })
    away.update({
        "def_st_td_rate": 0.4,
        "safety_rate": 0.1,
        "conversion_pat_p": 0.0,
        "conversion_two_p": 1.0,
        "conversion_no_p": 0.0,
    })
    out = simulate_game(model, game_id="TEAM-OVERRIDE", home_row=home, away_row=away, paths=10000, seed=71)
    assert out["model"]["home_def_st_td_rate"] == 0.0
    assert out["model"]["away_def_st_td_rate"] == pytest.approx(0.4)
    assert out["model"]["home_conversion_probabilities"] == (1.0, 0.0, 0.0)
    assert out["model"]["away_conversion_probabilities"] == (0.0, 1.0, 0.0)


def test_partial_or_invalid_team_conversion_override_fails_closed():
    model = fit()
    home = row(2022, 0.1, home=True, td=0, fg=0)
    away = row(2022, 0.1, home=False, td=0, fg=0)
    home["conversion_pat_p"] = 0.9
    with pytest.raises(ScoreCountsError, match="TEAM_CONVERSION_OVERRIDE_INCOMPLETE"):
        simulate_game(model, game_id="BAD-CONV", home_row=home, away_row=away, paths=100, seed=4)


def test_attempt2_fg_subset_is_supported_without_changing_td_identity():
    rows = training_rows()
    fg_alpha = FG_ATTEMPT2_ALPHA_GRID[-1]
    model = fit_poisson_ridge(
        rows,
        target="made_field_goals",
        alpha=fg_alpha,
        feature_names=FG_ATTEMPT2_FEATURE_NAMES,
    )
    assert model.feature_names == FG_ATTEMPT2_FEATURE_NAMES
    assert model.alpha == fg_alpha
    assert predict_mean(model, rows[0]) > 0

    fitted = fit_core(
        rows,
        shared_sigma=0.10,
        def_st_td_rate=0.08,
        safety_rate=0.015,
        conversion_probabilities=(0.92, 0.05, 0.03),
        source_manifest_sha256="a" * 64,
        code_identity="attempt2-subset-test",
        fg_feature_names=FG_ATTEMPT2_FEATURE_NAMES,
        fg_alphas=FG_ATTEMPT2_ALPHA_GRID,
    )
    assert fitted.td_model.feature_names == FEATURE_NAMES
    assert fitted.fg_model.feature_names == FG_ATTEMPT2_FEATURE_NAMES


def test_simulation_retains_team_td_components_used_to_build_scores():
    model = fit()
    home = row(2022, 0.8, home=True, td=0, fg=0)
    away = row(2022, -0.3, home=False, td=0, fg=0)
    a = simulate_game(model, game_id="TD-COMP", home_row=home, away_row=away, paths=10000, seed=19)
    b = simulate_game(model, game_id="TD-COMP", home_row=home, away_row=away, paths=10000, seed=19)
    assert np.array_equal(a["home_team_tds"], b["home_team_tds"])
    assert np.array_equal(a["away_team_tds"], b["away_team_tds"])
    assert len(a["home_team_tds"]) == 10000
    assert len(a["away_team_tds"]) == 10000
    assert np.all(a["home_team_tds"] >= 0)
    assert np.all(a["away_team_tds"] >= 0)
