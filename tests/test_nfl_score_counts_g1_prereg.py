import json
from pathlib import Path

PATH = Path("config/research/nfl_score_counts_g1_prereg_v1.json")


def load():
    return json.loads(PATH.read_text(encoding="utf-8"))


def test_is_new_family_not_v2k_attempt_six():
    x = load()
    assert x["family"] == "NFL_SCORE_COUNTS_G1"
    rel = x["relationship_to_v2k"]
    assert rel["v2k_final_status"] == "BUDGET_EXHAUSTED_NO_PASS"
    assert rel["attempts_used"] == 5
    assert rel["attempts_remaining"] == 0
    assert rel["extends_v2k_attempt_budget"] is False
    assert rel["reuses_v2k_attempt_ledger"] is False
    assert rel["old_v2l_revived"] is False


def test_forward_boundary_is_week5_no_backfill():
    x = load()["training_and_exposure"]
    assert x["fresh_forward_season"] == 2026
    assert x["fresh_forward_first_week"] == 5
    assert x["first_eligible_kickoff_utc"] == "2026-10-09T00:15:00Z"
    assert x["backfill_allowed"] is False
    assert x["historical_untouched_claim"] is False


def test_model_is_scoring_count_not_drive_terminal_model():
    x = load()
    spec = x["model_specification"]
    assert spec["offensive_td_and_fg_mean_model"]["family"] == "L2_REGULARIZED_POISSON_GLM_LOG_LINK"
    assert x["objective"].startswith("Generate one coherent NFL home/away final-score distribution")
    assert spec["final_score_formula"] == "6*TD + PAT_MADE + 2*TWO_POINT_MADE + 3*MADE_FG + 2*SAFETY"


def test_market_data_cannot_enter_distribution():
    x = load()
    assert x["market_derivation"]["sportsbook_quotes_as_model_features"] is False
    assert x["evaluation_market_binding"]["role"] == "EVALUATION_BENCHMARK_ONLY"
    assert x["evaluation_market_binding"]["prediction_must_exist_before_quote_binding"] is True
    assert x["evaluation_market_binding"]["line_and_price_cannot_change_model_distribution"] is True


def test_one_joint_distribution_owns_all_game_markets():
    x = load()
    expected = {"MONEYLINE","SPREAD","GAME_TOTAL","HOME_TEAM_TOTAL","AWAY_TEAM_TOTAL"}
    assert set(x["rng_and_simulation"]["one_joint_path_set_for"]) == expected
    assert x["market_derivation"]["independent_market_specific_probability_models"] is False


def test_rng_identity_and_forward_gates_are_frozen():
    x = load()
    r = x["rng_and_simulation"]
    assert r["bit_generator"] == "NUMPY_PCG64"
    assert r["root_seed_sha256"] == "e27030a04d79f28dfc7e708c9c79d873a91f09ece03034db68fd6e4328fad77c"
    assert r["root_seed_uint64_decimal"] == "16316594915016045197"
    assert r["paths_per_game"] == 50000
    gate = x["prospective_gate"]
    assert gate["minimum_completed_games"] == 160
    assert gate["calibration"] == {
        "slope_min": 0.90,
        "slope_max": 1.10,
        "intercept_abs_max": 0.03,
        "ece_max": 0.025,
    }
    assert gate["threshold_changes_after_first_forward_prediction"] == "FORBIDDEN"


def test_zero_authority_before_validation_and_promotion():
    a = load()["authority"]
    assert a["research_only"] is True
    assert not any(v for k, v in a.items() if k != "research_only")
