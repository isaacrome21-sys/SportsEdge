import json
from pathlib import Path


LOCK = Path("config/research/nfl_prop_usage_v1_fit_lock.json")


def load():
    return json.loads(LOCK.read_text())


def test_prop_usage_v1_fit_lock_keeps_2025_out_of_fit():
    cfg = load()
    assert cfg["status"] == "FROZEN_BEFORE_2025_PROP_OUTCOME_ACCESS"
    assert cfg["development"]["seasons"] == [2021, 2022, 2023, 2024]
    assert 2025 not in cfg["development"]["seasons"]
    assert cfg["development"]["market_data_in_fit"] is False
    assert cfg["model"]["shrinkage"]["hyperparameter_search"] is False
    assert cfg["model"]["shrinkage"]["tuned_on_2025"] is False


def test_candidate_is_usage_times_efficiency_with_fixed_history():
    cfg = load()
    model = cfg["model"]
    assert model["family"] == "FIXED_VOLUME_EFFICIENCY_MONTE_CARLO_V1"
    assert model["player_history"] == {
        "lookback_appearances": 8,
        "decay": 0.85,
        "cross_season_carry": True,
        "strictly_prior": True,
        "minimum_prior_appearances": 3,
    }
    assert model["primitives"]["passing_yards"] == [
        "pass_attempts", "completion_rate", "yards_per_completion"
    ]
    assert model["primitives"]["rushing_yards"] == [
        "rush_attempts", "yards_per_carry"
    ]
    assert model["primitives"]["receiving_yards"] == [
        "targets", "catch_rate", "yards_per_reception"
    ]
    assert model["simulation"]["n_sims"] == 20000
    assert model["simulation"]["gamma_shape"] == 2.0


def test_close_tape_is_immutable_dk_pre_kick_only():
    cfg = load()["market_binding"]
    assert cfg["provider"] == "DraftKings"
    assert cfg["source_commit"] == "d3fbfe1bece2f095e775f08d476cc5936ba37e13"
    assert cfg["selection"] == "LAST_PRE_KICKOFF_SNAPSHOT"
    assert cfg["lead_minutes"] == {"gt": 0, "lte": 15}
    assert cfg["paired_over_under_required"] is True
    assert cfg["line_used_for_grading_only"] is True
    assert cfg["weeks"] == list(range(1, 19))


def test_lineup_gate_never_uses_postgame_participation():
    gate = load()["lineup_gate"]
    assert gate["official_gamebook_not_active_required"] is True
    assert gate["gamebook_not_forward_capture"] is True
    assert gate["qb_pass_yards_requires_starting_qb"] is True
    assert gate["qb_starter_depth_dt_before_close_required"] is True
    assert gate["no_postgame_participation_inference"] is True
    assert gate["missing_or_unparseable_gamebook"] == "DROP_GAME_ZERO_ROWS"


def test_frozen_2025_gates_are_all_required_and_one_look():
    val = load()["validation"]
    assert val["one_look"] is True
    assert val["all_gates_must_pass"] is True
    assert val["failure_spends_window"] is True
    assert val["no_post_result_retune"] is True
    assert val["no_second_2025_look"] is True
    assert val["metrics"]["calibration"]["max"] == 0.06
    assert val["metrics"]["brier"]["pass_rule"] == "CANDIDATE_BRIER_LE_BASELINE_BRIER"
    assert val["metrics"]["inactive_missing"]["pass_rule"] == (
        "ZERO_ROWS_EMITTED_WHEN_OFFICIAL_NOT_ACTIVE_LIST_MISSING"
    )


def test_no_authority_created():
    assert all(value is False for value in load()["authority"].values())
