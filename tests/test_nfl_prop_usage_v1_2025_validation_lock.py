import json
from pathlib import Path

LOCK = Path("config/research/nfl_prop_usage_v1_2025_validation_lock.json")

def test_lock_binds_exact_fit_and_source_artifacts():
    cfg = json.loads(LOCK.read_text())
    assert cfg["status"] == "FROZEN_BEFORE_2025_OUTCOME_ACCESS"
    assert cfg["fit_identity"]["head_sha"] == "dfe1914d6c5b70e727c17273dabd0bb033dc816d"
    assert cfg["fit_identity"]["fit_artifact_sha256"] == "ef38c7101da0977f27b71a7cbbe40321149ee2e0fda3bb8371f04d8423c9c555"
    assert cfg["source_identity"]["head_sha"] == "438147dc660b9b62d54ad08511a441a7375cc650"
    assert cfg["source_identity"]["admitted_regular_season_games_with_strict_prekick_inactives"] == 52
    assert cfg["validation_window"]["status"] == "UNSPENT"

def test_lock_preserves_frozen_gates_and_fail_closed_cohort():
    cfg = json.loads(LOCK.read_text())
    assert cfg["cohort"]["missing_or_ambiguous_evidence"] == "ZERO_MODEL_ROWS"
    assert cfg["cohort"]["no_sample_filling"] is True
    assert cfg["probability"]["integer_line_behavior"] == "FAIL_CLOSED"
    assert cfg["gates"]["calibration_max"] == 0.06
    assert cfg["gates"]["required_scopes"] == [
        "passing_yards", "rushing_yards", "receiving_yards", "pooled"
    ]
    assert cfg["gates"]["brier_rule"] == "CANDIDATE_POOLED_BRIER_LE_DEVELOPMENT_POSITION_MARKET_BASELINE_POOLED_BRIER"
    assert cfg["reporting"]["minimum_n_gate"] is None
    assert cfg["validation_window"]["post_result_retune"] is False
    assert cfg["validation_window"]["second_look"] is False
    assert all(value is False for key, value in cfg["authority"].items() if key != "research_only")
