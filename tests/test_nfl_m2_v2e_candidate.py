from copy import deepcopy

import pytest

from sportsedge.sports.nfl.m2_v2e_candidate import (
    NFL_M2_V2E_CANDIDATE_MODEL_ID,
    NFLM2V2ECandidateModel,
    derive_nfl_m2_v2e_score_distribution,
    fit_nfl_m2_v2e_candidate,
)


def _row(season: int, shift: int = 0) -> dict:
    home_drives = 10 + (shift % 3)
    away_drives = 10 + ((shift + 1) % 3)
    return {
        "season": season,
        "home_state": {"offense": 0.10 + shift * 0.01, "defense": -0.03, "qb": 0.04},
        "away_state": {"offense": 0.03, "defense": 0.02 - shift * 0.01, "qb": 0.01},
        "home_drives": home_drives,
        "home_td_xp": 3,
        "home_td_2pt": 0,
        "home_td_no_try": 0,
        "home_fg": 2,
        "home_def_td_7_allowed": 0,
        "home_safety_allowed": 0,
        "home_no_score": home_drives - 5,
        "away_drives": away_drives,
        "away_td_xp": 2,
        "away_td_2pt": 0,
        "away_td_no_try": 0,
        "away_fg": 2,
        "away_def_td_7_allowed": 0,
        "away_safety_allowed": 0,
        "away_no_score": away_drives - 4,
    }


def _training() -> list[dict]:
    return [_row(2019 + index // 2, index) for index in range(8)]


def test_v2e_fits_discrete_possession_model_and_generates_integer_scores():
    model = fit_nfl_m2_v2e_candidate(_training())
    assert model.model_id == NFL_M2_V2E_CANDIDATE_MODEL_ID
    assert model.promotion_eligible is False
    assert sum(model.home_outcome_probabilities) == pytest.approx(1.0)
    assert sum(model.away_outcome_probabilities) == pytest.approx(1.0)

    paths = derive_nfl_m2_v2e_score_distribution(model, _row(2024), path_count=512)
    assert len(paths) == 512
    assert all(isinstance(path["home_score"], int) and isinstance(path["away_score"], int) for path in paths)
    assert all(path["home_score"] >= 0 and path["away_score"] >= 0 for path in paths)
    assert len({(path["home_score"], path["away_score"]) for path in paths}) > 10


def test_v2e_is_byte_semantics_deterministic():
    rows = _training()
    model_a = fit_nfl_m2_v2e_candidate(rows)
    model_b = fit_nfl_m2_v2e_candidate(deepcopy(rows))
    assert model_a == model_b
    assert derive_nfl_m2_v2e_score_distribution(model_a, _row(2024), path_count=512) == derive_nfl_m2_v2e_score_distribution(model_b, _row(2024), path_count=512)


def test_v2e_rejects_market_contamination_nested_or_top_level():
    rows = _training()
    contaminated = deepcopy(rows)
    contaminated[0]["spread_line"] = -3.0
    with pytest.raises(ValueError, match="NFL_M2_V2E_MARKET_DATA_PROHIBITED"):
        fit_nfl_m2_v2e_candidate(contaminated)

    contaminated = deepcopy(rows)
    contaminated[0]["home_state"]["closing_total"] = 46.5
    with pytest.raises(ValueError, match="NFL_M2_V2E_MARKET_DATA_PROHIBITED"):
        fit_nfl_m2_v2e_candidate(contaminated)


def test_v2e_requires_drive_outcomes_to_sum_exactly():
    rows = _training()
    rows[0]["home_no_score"] += 1
    with pytest.raises(ValueError, match="NFL_M2_V2E_DRIVE_OUTCOME_SUM_MISMATCH"):
        fit_nfl_m2_v2e_candidate(rows)


def test_v2e_heldout_result_fields_do_not_affect_generation():
    model = fit_nfl_m2_v2e_candidate(_training())
    game = _row(2024)
    stripped = {"home_state": game["home_state"], "away_state": game["away_state"]}
    mutated = deepcopy(stripped)
    mutated["home_score"] = 70
    mutated["away_score"] = 0
    assert derive_nfl_m2_v2e_score_distribution(model, stripped, path_count=512) == derive_nfl_m2_v2e_score_distribution(model, mutated, path_count=512)


def test_v2e_key_numbers_emerge_without_injected_key_mass():
    model = fit_nfl_m2_v2e_candidate(_training())
    paths = derive_nfl_m2_v2e_score_distribution(model, _row(2024), path_count=4096)
    margins = [path["home_score"] - path["away_score"] for path in paths]
    assert 3 in margins or -3 in margins
    assert 7 in margins or -7 in margins


def test_v2e_sampler_preserves_poisson_drive_mean_instead_of_compressing_unit_interval():
    model = NFLM2V2ECandidateModel(
        model_id="nfl_m2_possession_discrete_v2e_candidate",
        feature_contract="NFL_M2_V2E_MARKET_BLIND_DRIVE_STATE_V1",
        distribution_contract="NFL_M2_V2E_POSSESSION_DISCRETE_SCORE_V1",
        train_seasons=(2020,),
        home_drive_mean=10.0,
        away_drive_mean=10.0,
        home_outcome_probabilities=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
        away_outcome_probabilities=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
        home_state_coefficients=(),
        away_state_coefficients=(),
        laplace_alpha=1.0,
        promotion_eligible=False,
    )
    paths = derive_nfl_m2_v2e_score_distribution(model, {}, path_count=4096)
    home_drive_mean = sum(path["home_score"] / 3.0 for path in paths) / len(paths)
    away_drive_mean = sum(path["away_score"] / 3.0 for path in paths) / len(paths)
    assert home_drive_mean == pytest.approx(10.0, abs=0.05)
    assert away_drive_mean == pytest.approx(10.0, abs=0.05)


def test_v2e_safety_on_home_possession_scores_for_away_team():
    model = NFLM2V2ECandidateModel(
        model_id="nfl_m2_possession_discrete_v2e_candidate",
        feature_contract="NFL_M2_V2E_MARKET_BLIND_DRIVE_STATE_V1",
        distribution_contract="NFL_M2_V2E_POSSESSION_DISCRETE_SCORE_V1",
        train_seasons=(2020,),
        home_drive_mean=10.0,
        away_drive_mean=10.0,
        home_outcome_probabilities=(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        away_outcome_probabilities=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        home_state_coefficients=(),
        away_state_coefficients=(),
        laplace_alpha=1.0,
        promotion_eligible=False,
    )
    paths = derive_nfl_m2_v2e_score_distribution(model, {}, path_count=256)
    assert all(path["home_score"] == 0 for path in paths)
    assert any(path["away_score"] > 0 for path in paths)
    assert all(path["away_score"] % 2 == 0 for path in paths)


def test_v2e_defensive_td_on_home_possession_scores_for_away_team():
    model = NFLM2V2ECandidateModel(
        model_id="nfl_m2_possession_discrete_v2e_candidate",
        feature_contract="NFL_M2_V2E_MARKET_BLIND_DRIVE_STATE_V1",
        distribution_contract="NFL_M2_V2E_POSSESSION_DISCRETE_SCORE_V1",
        train_seasons=(2020,),
        home_drive_mean=10.0,
        away_drive_mean=10.0,
        home_outcome_probabilities=(0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0),
        away_outcome_probabilities=(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0),
        home_state_coefficients=(),
        away_state_coefficients=(),
        laplace_alpha=1.0,
        promotion_eligible=False,
    )
    paths = derive_nfl_m2_v2e_score_distribution(model, {}, path_count=256)
    assert all(path["home_score"] == 0 for path in paths)
    assert any(path["away_score"] > 0 for path in paths)
    assert all(path["away_score"] % 7 == 0 for path in paths)
