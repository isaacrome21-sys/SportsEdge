from copy import deepcopy

import pytest

from sportsedge.sports.nfl.m2_v2d_candidate import (
    NFL_M2_V2D_CANDIDATE_MODEL_ID,
    derive_nfl_m2_v2d_score_distribution,
    fit_nfl_m2_v2d_candidate,
)


def _features(seed: float, qb: str) -> dict:
    return {
        "feature_contract": "NFL_M2_V1_MARKET_BLIND",
        "adj_off_epa": 0.10 + seed,
        "adj_def_epa": -0.05 + seed / 2,
        "pass_epa": 0.12 + seed,
        "rush_epa": 0.02 + seed,
        "pressure_for": 0.30 + seed / 10,
        "pressure_allowed": 0.25 + seed / 10,
        "success_rate": 0.45 + seed / 20,
        "explosive_rate": 0.11 + seed / 30,
        "rest_diff_days": seed,
        "travel_miles": 100.0 + seed * 10,
        "timezone_crossings": 0.0,
        "short_week": 0.0,
        "bye_week": 0.0,
        "wind_mph": 5.0 + seed,
        "roof_closed": 0.0,
        "qb_id": qb,
        "qb_adjustment": seed / 10,
        "prior_efficiency": 0.05 + seed / 20,
        "prior_weight": 0.5,
        "feature_asof_ts": "2025-09-01T12:00:00+00:00",
    }


def _row(season: int, seed: float, home: int, away: int) -> dict:
    return {
        "season": season,
        "home_features": _features(seed, f"H{season}"),
        "away_features": _features(-seed / 2, f"A{season}"),
        "home_score": home,
        "away_score": away,
    }


def _rows() -> list[dict]:
    return [
        _row(2020, -1.0, 20, 17),
        _row(2020, -0.5, 14, 24),
        _row(2021, 0.0, 27, 20),
        _row(2021, 0.5, 31, 28),
        _row(2022, 1.0, 35, 17),
        _row(2022, 1.5, 23, 21),
    ]


def test_v2d_fits_direct_scores_and_replays_integer_paths():
    rows = _rows()
    model = fit_nfl_m2_v2d_candidate(rows)
    assert model.model_id == NFL_M2_V2D_CANDIDATE_MODEL_ID
    paths = derive_nfl_m2_v2d_score_distribution(model, rows[-1])
    assert len(paths) == len(rows)
    assert all(isinstance(path["home_score"], int) and isinstance(path["away_score"], int) for path in paths)
    assert all(path["home_score"] >= 0 and path["away_score"] >= 0 for path in paths)


def test_v2d_market_fields_are_rejected():
    rows = _rows()
    rows[0]["home_features"]["spread"] = -3.0
    with pytest.raises(ValueError, match="M2_MARKET_DATA_PROHIBITED"):
        fit_nfl_m2_v2d_candidate(rows)


def test_v2d_heldout_outcome_mutation_cannot_change_distribution():
    train = _rows()
    heldout = _row(2023, 2.0, 10, 40)
    mutated = deepcopy(heldout)
    mutated["home_score"] = 70
    mutated["away_score"] = 0
    model = fit_nfl_m2_v2d_candidate(train)
    assert derive_nfl_m2_v2d_score_distribution(model, heldout) == derive_nfl_m2_v2d_score_distribution(model, mutated)


def test_v2d_fit_is_deterministic():
    rows = _rows()
    assert fit_nfl_m2_v2d_candidate(rows) == fit_nfl_m2_v2d_candidate(deepcopy(rows))
