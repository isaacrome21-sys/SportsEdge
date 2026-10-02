import copy

import pytest

from sportsedge.research.nfl_game_script_v2_validate_2025 import (
    CANONICAL_ARTIFACT_SHA256,
    CANONICAL_FIT_HEAD,
    NflGameScriptV2ValidationError,
    build_validation_team_games,
    expected_validation_uri,
    load_validation_lock,
    score_evaluation_rows,
    script_multipliers,
    validate_2025,
)


def source_receipt():
    return {
        "season": 2025,
        "source_uri": expected_validation_uri(),
        "raw_sha256": "a" * 64,
        "retrieved_at": "2026-10-01T20:00:00+00:00",
        "raw_bytes": 123456,
    }


def test_validation_lock_binds_exact_canonical_fit_and_one_look():
    cfg = load_validation_lock()
    assert cfg["status"] == "FROZEN_BEFORE_2025_ACCESS"
    assert cfg["canonical_fit"]["artifact_sha256"] == CANONICAL_ARTIFACT_SHA256
    assert cfg["canonical_fit"]["fit_head_sha"] == CANONICAL_FIT_HEAD
    assert cfg["canonical_fit"]["selected_alpha"] == 10.0
    assert cfg["canonical_fit"]["n_team_games"] == 2560
    assert cfg["pregame_baseline"]["history_scope"] == "2025_REGULAR_SEASON_ONLY"
    assert cfg["pregame_baseline"]["prior_team_games"] == 8
    assert cfg["pregame_baseline"]["cross_season_carry"] is False
    assert cfg["one_look"]["no_second_2025_look"] is True


def test_canonical_multiplier_values_match_fit_artifact():
    cfg = load_validation_lock()
    loss = script_multipliers(cfg, final_margin=-14)
    tie = script_multipliers(cfg, final_margin=0)
    win = script_multipliers(cfg, final_margin=14)

    assert loss["pass_multiplier"] == pytest.approx(1.1354632565249891)
    assert loss["rush_multiplier"] == pytest.approx(0.8050117269577407)
    assert tie["pass_multiplier"] == pytest.approx(1.0357030621140724)
    assert tie["rush_multiplier"] == pytest.approx(1.028055216179782)
    assert win["pass_multiplier"] == pytest.approx(0.8600285012351832)
    assert win["rush_multiplier"] == pytest.approx(1.1871596925481345)


def test_validation_pbp_ignores_market_columns_and_classifies_scrambles_once():
    base = []
    for kind in ("pass", "rush", "scramble", "kneel"):
        base.append(
            {
                "season": 2025,
                "season_type": "REG",
                "game_id": "2025_01_AAA_BBB",
                "posteam": "AAA",
                "posteam_type": "away",
                "home_score": 17,
                "away_score": 24,
                "pass_attempt": 1 if kind == "pass" else 0,
                "rush_attempt": 1 if kind in {"rush", "scramble", "kneel"} else 0,
                "qb_scramble": 1 if kind == "scramble" else 0,
                "qb_kneel": 1 if kind == "kneel" else 0,
                "spread_line": 3.5,
                "total_line": 44.5,
                "vegas_wp": 0.44,
                "sportsbook_probability": 0.55,
            }
        )
    mutated = copy.deepcopy(base)
    for row in mutated:
        row["spread_line"] = -99
        row["total_line"] = 1
        row["vegas_wp"] = 0.99
        row["sportsbook_probability"] = 0.01

    a = build_validation_team_games(base)
    b = build_validation_team_games(mutated)
    assert a == b
    assert a[0]["pass_plays"] == 1
    assert a[0]["rush_plays"] == 2
    assert a[0]["final_margin"] == 7
    assert a[0]["week"] == 1


def test_non_2025_validation_row_fails_closed():
    row = {
        "season": 2024,
        "season_type": "REG",
        "game_id": "2024_01_AAA_BBB",
        "posteam": "AAA",
        "posteam_type": "away",
        "home_score": 17,
        "away_score": 24,
        "pass_attempt": 1,
        "rush_attempt": 0,
        "qb_scramble": 0,
        "qb_kneel": 0,
    }
    with pytest.raises(NflGameScriptV2ValidationError, match="OUTSIDE_2025"):
        build_validation_team_games([row])


def synthetic_team_games():
    rows = []
    margins = [-7, 3, -3, 7, 0, -10, 10, -1, -14, 14]
    for week, margin in enumerate(margins, start=1):
        rows.append(
            {
                "season": 2025,
                "week": week,
                "game_id": f"2025_{week:02d}_AAA_BBB",
                "team": "AAA",
                "final_margin": margin,
                "pass_plays": 34 + (week % 3),
                "rush_plays": 27 + (week % 4),
            }
        )
    return rows


def test_first_eight_team_games_are_unscored_and_history_is_strictly_prior():
    artifact = validate_2025(
        synthetic_team_games(),
        source_receipt=source_receipt(),
    )
    assert artifact["validation_window_spent"] is True
    assert artifact["n_evaluated_team_games"] == 2
    eval_rows = artifact["evaluation_rows"]
    assert [row["week"] for row in eval_rows] == [9, 10]
    assert eval_rows[0]["history_game_ids"] == [
        f"2025_{week:02d}_AAA_BBB" for week in range(1, 9)
    ]
    assert eval_rows[1]["history_game_ids"] == [
        f"2025_{week:02d}_AAA_BBB" for week in range(2, 10)
    ]
    assert artifact["history_policy"]["cross_season_carry"] is False
    assert artifact["canonical_fit_artifact_sha256"] == CANONICAL_ARTIFACT_SHA256


def test_gate_math_passes_only_when_all_frozen_rules_pass():
    cfg = load_validation_lock()
    good = [
        {
            "baseline_pass_error": 4.0,
            "baseline_rush_error": -4.0,
            "script_pass_error": 2.0,
            "script_rush_error": -2.0,
            "script_pass_signed_error": 0.5,
            "script_rush_signed_error": -0.5,
        },
        {
            "baseline_pass_error": -4.0,
            "baseline_rush_error": 4.0,
            "script_pass_error": -2.0,
            "script_rush_error": 2.0,
            "script_pass_signed_error": -0.5,
            "script_rush_signed_error": 0.5,
        },
    ]
    scored = score_evaluation_rows(good, lock=cfg)
    assert scored["passed"] is True
    assert all(scored["gates"].values())
    assert scored["combined_mae_relative_improvement"] == pytest.approx(0.5)

    bad = copy.deepcopy(good)
    for row in bad:
        row["script_rush_error"] = row["baseline_rush_error"] * 1.1
        row["script_rush_signed_error"] = 2.0
    failed = score_evaluation_rows(bad, lock=cfg)
    assert failed["passed"] is False
    assert failed["gates"]["rush_mae_not_worsen"] is False
    assert failed["gates"]["rush_mean_error_abs"] is False


def test_bad_source_identity_fails_before_scoring():
    bad = source_receipt()
    bad["source_uri"] = "https://example.com/2025.csv"
    with pytest.raises(NflGameScriptV2ValidationError, match="SOURCE_URI_INVALID"):
        validate_2025(synthetic_team_games(), source_receipt=bad)
