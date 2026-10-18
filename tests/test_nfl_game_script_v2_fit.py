import copy

import pytest

from sportsedge.research.nfl_game_script_v2_fit import (
    ALPHAS,
    EXPOSED_V1_SEASONS,
    FIT_SEASONS,
    NflGameScriptV2Error,
    VALIDATION_SEASON,
    build_team_game_rows,
    expected_pbp_uri,
    fit_game_script_v2,
    script_multipliers,
    validate_artifact,
)


def receipts():
    return [
        {
            "season": season,
            "source_uri": expected_pbp_uri(season),
            "raw_sha256": f"{season:064x}"[-64:],
            "retrieved_at": "2026-10-01T12:00:00+00:00",
            "raw_bytes": 123456,
        }
        for season in FIT_SEASONS
    ]


def synthetic_team_games():
    rows = []
    # Deterministic smooth relationship: losing teams pass more and rush less.
    margins = (-21, -14, -10, -7, -3, 0, 3, 7, 10, 14, 21, -1, 1, 17, -17, 5)
    for season in FIT_SEASONS:
        for team_i in range(16):
            team = f"T{team_i:02d}"
            for game_i, margin in enumerate(margins):
                pass_plays = round(34.0 - 0.32 * margin + 0.002 * margin * margin)
                rush_plays = round(28.0 + 0.27 * margin + 0.001 * margin * margin)
                rows.append({
                    "season": season,
                    "game_id": f"{season}_{team}_{game_i:02d}",
                    "team": team,
                    "final_margin": margin,
                    "pass_plays": max(10, pass_plays),
                    "rush_plays": max(10, rush_plays),
                })
    return rows


def test_fit_window_is_fresh_and_validation_is_untouched():
    assert FIT_SEASONS == (2011, 2012, 2013, 2014, 2015)
    assert EXPOSED_V1_SEASONS == tuple(range(2016, 2025))
    assert VALIDATION_SEASON == 2025
    assert set(FIT_SEASONS).isdisjoint(EXPOSED_V1_SEASONS)
    assert VALIDATION_SEASON not in FIT_SEASONS


def test_raw_market_columns_cannot_affect_team_game_reduction():
    base = []
    for game_i in range(2):
        for kind in ("pass", "rush", "kneel", "scramble"):
            base.append({
                "season": 2015,
                "season_type": "REG",
                "game_id": f"2015_0{game_i+1}_AAA_BBB",
                "posteam": "AAA",
                "posteam_type": "home",
                "home_score": 24,
                "away_score": 17,
                "pass_attempt": 1 if kind == "pass" else 0,
                "rush_attempt": 1 if kind in {"rush", "kneel", "scramble"} else 0,
                "qb_scramble": 1 if kind == "scramble" else 0,
                "qb_kneel": 1 if kind == "kneel" else 0,
                "spread_line": -3.5,
                "total_line": 44.5,
                "vegas_wp": 0.72,
            })
    mutated = copy.deepcopy(base)
    for row in mutated:
        row["spread_line"] = 99
        row["total_line"] = 12
        row["vegas_wp"] = 0.01
    assert build_team_game_rows(base) == build_team_game_rows(mutated)


def test_v2_fit_is_deterministic_and_selects_declared_alpha():
    games = synthetic_team_games()
    a = fit_game_script_v2(games, source_receipts=receipts())
    b = fit_game_script_v2(list(reversed(games)), source_receipts=list(reversed(receipts())))
    assert a == b
    validate_artifact(a)
    assert a["cv"]["selected_alpha"] in ALPHAS
    assert [row["alpha"] for row in a["cv"]["rows"]] == list(ALPHAS)
    assert a["validation_season_accessed"] is False
    assert a["status"] == "FITTED_RESEARCH_ONLY_NOT_VALIDATED"


def test_synthetic_fit_learns_direction_without_monotonic_constraint():
    artifact = fit_game_script_v2(synthetic_team_games(), source_receipts=receipts())
    loss = script_multipliers(artifact, final_margin=-14)
    even = script_multipliers(artifact, final_margin=0)
    win = script_multipliers(artifact, final_margin=14)

    assert loss["pass_multiplier"] > even["pass_multiplier"] > win["pass_multiplier"]
    assert loss["rush_multiplier"] < even["rush_multiplier"] < win["rush_multiplier"]


def test_exposed_v1_and_validation_rows_fail_closed():
    games = synthetic_team_games()
    for bad_season in (2016, 2024, 2025):
        bad = list(games) + [{
            "season": bad_season,
            "game_id": f"{bad_season}_01_AAA_BBB",
            "team": "AAA",
            "final_margin": 3,
            "pass_plays": 35,
            "rush_plays": 28,
        }]
        with pytest.raises(NflGameScriptV2Error, match="FIT_ROW_OUTSIDE_FRESH_WINDOW"):
            fit_game_script_v2(bad, source_receipts=receipts())


def test_source_helper_rejects_nonfit_seasons():
    assert expected_pbp_uri(2011).endswith("play_by_play_2011.csv")
    for bad in (2010, 2016, 2024, 2025):
        with pytest.raises(NflGameScriptV2Error, match="FIT_SOURCE_SEASON_FORBIDDEN"):
            expected_pbp_uri(bad)


def test_tamper_fails_closed():
    artifact = fit_game_script_v2(synthetic_team_games(), source_receipts=receipts())
    bad = copy.deepcopy(artifact)
    bad["pass_model"]["coef"][1] += 0.01
    with pytest.raises(NflGameScriptV2Error, match="ARTIFACT_SHA_MISMATCH"):
        validate_artifact(bad)
