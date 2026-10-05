import json
from math import exp
from pathlib import Path
import subprocess

PARENT = Path("config/research/nfl_score_counts_g1_prereg_v1.json")
ADDENDUM = Path("config/research/nfl_score_counts_g1_prereg_addendum_v2.json")


def load():
    return json.loads(ADDENDUM.read_text(encoding="utf-8"))


def test_parent_bytes_are_immutably_bound():
    cfg = load()
    got = subprocess.check_output(["git", "hash-object", str(PARENT)], text=True).strip()
    assert got == cfg["parent"]["git_blob_sha1"]
    assert cfg["parent"]["relationship"] == "VERSIONED_CLARIFICATION_ONLY_PARENT_BYTES_UNCHANGED"


def test_sigma_selection_identifies_covariance_not_mean_score():
    cfg = load()["overrides"]["shared_game_latent"]
    assert cfg["selection_metric"] == "MEAN_SQUARED_ERROR_OBSERVED_RESIDUAL_PRODUCT_VS_IMPLIED_COVARIANCE"
    assert cfg["candidate_sigma_grid"] == [0.0, 0.1, 0.2, 0.3]
    assert cfg["minimum_prior_training_seasons"] == 3
    assert cfg["validation_seasons"] == [2021, 2022, 2023, 2024, 2025]
    assert cfg["market_data_used"] is False
    mu_h, mu_a = 3.1, 2.8
    implied = [mu_h * mu_a * (exp(s * s) - 1.0) for s in cfg["candidate_sigma_grid"]]
    assert implied[0] == 0.0
    assert implied == sorted(implied)
    assert len(set(implied)) == len(implied)


def test_rare_score_and_conversion_priors_are_frozen_before_scoring():
    cfg = load()["overrides"]
    assert cfg["rare_scores"]["prior_exposure_team_games"] == 25
    conv = cfg["conversion_model"]
    assert conv["team_specific_minimum_prior_touchdowns"] == 50
    assert conv["team_prior_strength_touchdowns"] == 25
    assert conv["probability_mass_must_equal_one"] is True


def test_forward_boundary_and_zero_authority_are_preserved():
    cfg = load()
    preserved = cfg["preserved_parent_contract"]
    assert preserved["fresh_forward_first_week"] == 5
    assert preserved["first_eligible_kickoff_utc"] == "2026-10-09T00:15:00Z"
    assert preserved["backfill_allowed"] is False
    assert preserved["prospective_gate_unchanged"] is True
    assert preserved["research_development_budget_max"] == 3
    assert not any(value for key, value in cfg["authority"].items() if key != "research_only")
