import copy

import pytest

from sportsedge.research.nfl_game_script_v2_fit import (
    ALPHAS,
    DEVELOPMENT_SEASONS,
    EXPOSED_V1_SEASONS,
    NflGameScriptV2Error,
    build_team_game_rows,
    expected_pbp_uri,
    fit_game_script_v2,
    load_prelock,
    margin_basis,
    script_multipliers,
    select_alpha,
    validate_artifact,
)


def receipts():
    return [
        {
            "season": season,
            "source_uri": expected_pbp_uri(season),
            "raw_sha256": f"{season:064x}"[-64:],
            "retrieved_at": f"2026-10-01T13:{season % 60:02d}:00+00:00",
            "raw_bytes": 1000 + season,
        }
        for season in DEVELOPMENT_SEASONS
    ]


def synthetic_games():
    rows = []
    margins = (-21, -14, -10, -7, -3, 0, 3, 7, 10, 14, 21, 28)
    for season in DEVELOPMENT_SEASONS:
        for team_i in range(12):
            team = f"T{team_i:02d}"
            for game_i, margin in enumerate(margins):
                # Smooth relation with modest season/team noise.
                pass_plays = round(34.0 - 0.22 * margin + 0.15 * (season - 2013) + (team_i % 3 - 1) * 0.4)
                rush_plays = round(28.0 + 0.20 * margin - 0.10 * (season - 2013) + (team_i % 2) * 0.4)
                rows.append(
                    {
                        "season": season,
                        "game_id": f"{season}_{team}_{game_i:02d}",
                        "team": team,
                        "final_margin": margin,
                        "pass_plays": max(1, pass_plays),
                        "rush_plays": max(1, rush_plays),
                    }
                )
    return rows


def test_prelock_uses_fresh_window_and_keeps_exposed_years_out():
    cfg = load_prelock()
    assert cfg["fit_window"]["seasons"] == list(DEVELOPMENT_SEASONS)
    assert cfg["excluded_from_v2_fit_or_selection"]["seasons"] == list(EXPOSED_V1_SEASONS)
    assert cfg["validation_window"]["season"] == 2025
    assert cfg["validation_window"]["status"] == "CLEAN_UNUSED_BY_V1"
    assert not (set(DEVELOPMENT_SEASONS) & set(EXPOSED_V1_SEASONS))


def test_margin_basis_is_fixed_and_six_dimensional():
    assert margin_basis(0).shape == (6,)
    assert margin_basis(-20).tolist() == [-20.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert margin_basis(20).tolist() == [20.0, 34.0, 27.0, 20.0, 13.0, 6.0]


def test_market_columns_are_ignored_before_aggregation():
    base = []
    for game_i in range(2):
        for kind in ("pass", "rush", "scramble", "kneel"):
            base.append(
                {
                    "season": 2015,
                    "season_type": "REG",
                    "game_id": f"2015_0{game_i + 1}_AAA_BBB",
                    "posteam": "AAA",
                    "posteam_type": "home",
                    "home_score": 24,
                    "away_score": 17,
                    "pass_attempt": 1 if kind == "pass" else 0,
                    "rush_attempt": 1 if kind in {"rush", "scramble", "kneel"} else 0,
                    "qb_scramble": 1 if kind == "scramble" else 0,
                    "qb_kneel": 1 if kind == "kneel" else 0,
                    "spread_line": -3.5,
                    "total_line": 44.5,
                    "vegas_wp": 0.63,
                }
            )
    mutated = copy.deepcopy(base)
    for row in mutated:
        row["spread_line"] = 99
        row["total_line"] = 11
        row["vegas_wp"] = 0.01

    assert build_team_game_rows(base) == build_team_game_rows(mutated)
    out = build_team_game_rows(base)
    assert all(row["pass_plays"] == 1 for row in out)
    assert all(row["rush_plays"] == 2 for row in out)


def test_alpha_selection_is_from_frozen_grid_only():
    rows = synthetic_games()
    artifact = fit_game_script_v2(rows, source_receipts=receipts())
    selected = artifact["alpha_selection"]["selected_alpha"]
    assert selected in ALPHAS
    assert [x["alpha"] for x in artifact["alpha_selection"]["candidates"]] == list(ALPHAS)


def test_fit_is_deterministic_and_learns_sensible_direction():
    games = synthetic_games()
    a = fit_game_script_v2(games, source_receipts=receipts())
    b = fit_game_script_v2(list(reversed(games)), source_receipts=list(reversed(receipts())))
    assert a == b
    validate_artifact(a)

    loss = script_multipliers(a, final_margin=-14)
    win = script_multipliers(a, final_margin=14)
    assert loss["pass_multiplier"] > win["pass_multiplier"]
    assert loss["rush_multiplier"] < win["rush_multiplier"]

    assert a["fit_window"]["validation_season_accessed"] is False
    assert a["authority"]["validated_2025"] is False
    assert a["authority"]["creates_model_p"] is False


def test_exposed_v1_or_2025_rows_fail_closed():
    games = synthetic_games()
    games.append(
        {
            "season": 2016,
            "game_id": "2016_X",
            "team": "AAA",
            "final_margin": 3,
            "pass_plays": 34,
            "rush_plays": 28,
        }
    )
    with pytest.raises(NflGameScriptV2Error, match="OUTSIDE_DEVELOPMENT_WINDOW:2016"):
        fit_game_script_v2(games, source_receipts=receipts())

    games = synthetic_games()
    games.append(
        {
            "season": 2025,
            "game_id": "2025_X",
            "team": "AAA",
            "final_margin": 3,
            "pass_plays": 34,
            "rush_plays": 28,
        }
    )
    with pytest.raises(NflGameScriptV2Error, match="OUTSIDE_DEVELOPMENT_WINDOW:2025"):
        fit_game_script_v2(games, source_receipts=receipts())


def test_every_source_receipt_is_required():
    with pytest.raises(NflGameScriptV2Error, match="SOURCE_RECEIPTS_MISSING:2015"):
        fit_game_script_v2(synthetic_games(), source_receipts=receipts()[:-1])


def test_tampered_artifact_fails_closed():
    artifact = fit_game_script_v2(synthetic_games(), source_receipts=receipts())
    bad = copy.deepcopy(artifact)
    bad["model"]["pass_ratio"]["coef"][0] += 0.01
    with pytest.raises(NflGameScriptV2Error, match="ARTIFACT_SHA_MISMATCH"):
        validate_artifact(bad)
