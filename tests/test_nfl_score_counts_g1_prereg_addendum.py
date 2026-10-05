import json
from pathlib import Path

ADDENDUM = Path("config/research/nfl_score_counts_g1_prereg_addendum_v1.json")
PARENT = Path("config/research/nfl_score_counts_g1_prereg_v1.json")


def load():
    return json.loads(ADDENDUM.read_text(encoding="utf-8"))


def test_addendum_binds_frozen_parent_without_rewriting_it():
    x = load()
    assert x["parent_prereg"]["git_blob_sha1"] == "65f27bcc3ece8da6a4e642ee5b4e330525cd7a8a"
    assert x["parent_prereg"]["schema"] == "SPORTSEDGE_NFL_SCORE_COUNTS_G1_PREREG_V1"
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    assert parent["model_specification"]["shared_game_latent"]["selection"] == (
        "DEVELOPMENT_ONLY_EXPANDING_SEASON_CV_JOINT_SCORE_RMSE"
    )


def test_defect_is_declared_before_any_attempt_or_forward_outcome():
    x = load()
    d = x["correction_reason"]
    assert d["defect"] == "NON_IDENTIFYING_FOR_MEAN_PRESERVING_LATENT"
    assert d["discovered_before_any_score_counts_historical_attempt"] is True
    assert d["score_counts_attempts_used_at_discovery"] == 0
    assert d["forward_2026_outcomes_used"] is False
    assert d["market_data_used"] is False


def test_replacement_is_covariance_identified_and_frozen_to_existing_grid():
    x = load()["replacement"]
    assert x["method"] == "DEVELOPMENT_ONLY_OOF_SHARED_COUNT_RESIDUAL_COVARIANCE_MOMENT_MATCH"
    assert x["per_team_shared_count"] == "OFFENSE_TOUCHDOWNS + MADE_FIELD_GOALS"
    assert x["grid"] == [0.0, 0.10, 0.20, 0.30]
    assert "SUM(home_residual*away_residual)" in x["latent_variance_estimator"]
    assert x["zero_or_negative_cross_covariance"].startswith("Select sigma 0.0")
    assert x["denominator_zero"] == "FAIL_CLOSED_NO_ATTEMPT_SCORE"
    assert x["sportsbook_fields_allowed"] is False
    assert x["2026_weeks_allowed"] is False


def test_only_sigma_selection_semantics_are_amended_and_authority_stays_zero():
    x = load()
    assert len(x["unchanged_contracts"]) >= 9
    a = x["authority"]
    assert a["research_only"] is True
    assert a["consumes_development_attempt"] is False
    assert not any(v for k, v in a.items() if k not in {"research_only", "consumes_development_attempt"})
