import copy

import pytest

from sportsedge.research.nfl_prop_usage_v1_fit import (
    DEV_SEASONS,
    NflPropUsageV1FitError,
    fit_prop_usage_v1,
    load_freeze,
    select_hyperparameters,
    validate_artifact,
)


def rows():
    out = []
    positions = ["QB", "RB", "WR", "TE"]
    for season in DEV_SEASONS:
        for p_i, pos in enumerate(positions):
            for player_i in range(3):
                pid = f"{season}_{pos}_{player_i}"
                team = f"T{(p_i * 3 + player_i) % 8}"
                for week in range(1, 13):
                    attempts = 31 + player_i + (week % 3) if pos == "QB" else 0
                    passing_yards = attempts * (7.0 + 0.1 * player_i) if pos == "QB" else 0
                    carries = (
                        14 + player_i + week % 3 if pos in {"RB"}
                        else 4 + week % 2 if pos == "QB"
                        else 1 if pos == "WR" else 0
                    )
                    rushing_yards = carries * (4.1 + 0.1 * player_i)
                    targets = (
                        7 + player_i + week % 3 if pos in {"WR", "TE"}
                        else 4 + week % 2 if pos == "RB"
                        else 0
                    )
                    receiving_yards = targets * (8.5 + 0.2 * player_i)
                    out.append({
                        "season": season, "week": week, "season_type": "REG",
                        "player_id": pid, "player_display_name": pid,
                        "position": pos, "team": team,
                        "attempts": attempts, "passing_yards": passing_yards,
                        "carries": carries, "rushing_yards": rushing_yards,
                        "targets": targets, "receiving_yards": receiving_yards,
                    })
    return out


def env():
    return {
        (season, week, f"T{team_i}"): 20.0 + (week % 5) + team_i * 0.1
        for season in DEV_SEASONS
        for week in range(1, 13)
        for team_i in range(8)
    }


def receipt():
    return {
        "games": {"sha256": "a" * 64},
        **{f"player_stats_{s}": {"sha256": f"{s:064x}"[-64:]} for s in DEV_SEASONS},
    }


def test_freeze_keeps_2025_unread_and_dev_window_fixed():
    cfg = load_freeze()
    assert cfg["development"]["seasons"] == list(DEV_SEASONS)
    assert cfg["validation"]["season"] == 2025
    assert cfg["validation"]["status"] == "UNTOUCHED"
    assert cfg["validation"]["model_scoring_in_this_fit_step"] is False
    assert cfg["future_2025_gate_interpretation"]["post_result_retune"] is False
    assert cfg["future_2025_gate_interpretation"]["second_2025_look"] is False


def test_fit_is_deterministic_and_research_only():
    a = fit_prop_usage_v1(
        rows(), env(),
        source_receipts=receipt(),
        attempt9_artifact_sha256="b" * 64,
    )
    b = fit_prop_usage_v1(
        list(reversed(rows())), env(),
        source_receipts=receipt(),
        attempt9_artifact_sha256="b" * 64,
    )
    assert a == b
    validate_artifact(a)
    assert a["validation_season_accessed"] is False
    assert set(a["markets"]) == {"passing_yards", "rushing_yards", "receiving_yards"}
    assert a["authority"]["creates_model_p"] is False
    for market in a["markets"].values():
        assert market["selected"]["n_oof"] > 0
        assert market["oof_residual_sigma_pooled"] > 0


def test_hyperparameter_selection_only_uses_frozen_grid():
    cfg = load_freeze()
    selected, diagnostics = select_hyperparameters(rows(), env(), cfg)
    for market, winner in selected.items():
        assert winner["history_games"] in cfg["hyperparameter_search"]["history_games"]
        assert winner["decay"] in cfg["hyperparameter_search"]["decay"]
        assert winner["efficiency_prior_opportunities"] in cfg["hyperparameter_search"]["efficiency_prior_opportunities"]
        assert winner["script_gamma"] in cfg["hyperparameter_search"]["script_gamma"]
        expected = (
            len(cfg["hyperparameter_search"]["history_games"])
            * len(cfg["hyperparameter_search"]["decay"])
            * len(cfg["hyperparameter_search"]["efficiency_prior_opportunities"])
            * len(cfg["hyperparameter_search"]["script_gamma"])
        )
        assert len(diagnostics[market]) == expected


def test_2025_row_fails_before_any_fit():
    bad = rows()
    row = copy.deepcopy(bad[-1])
    row["season"] = 2025
    bad.append(row)
    with pytest.raises(NflPropUsageV1FitError, match="OUTSIDE_DEVELOPMENT:2025"):
        fit_prop_usage_v1(
            bad, env(),
            source_receipts=receipt(),
            attempt9_artifact_sha256="b" * 64,
        )


def test_market_contaminated_or_missing_columns_are_not_accepted_as_model_fields():
    bad = rows()
    bad[0] = dict(bad[0])
    bad[0].pop("targets")
    with pytest.raises(NflPropUsageV1FitError, match="PLAYER_STATS_COLUMNS_MISSING:targets"):
        fit_prop_usage_v1(
            bad, env(),
            source_receipts=receipt(),
            attempt9_artifact_sha256="b" * 64,
        )


def test_artifact_tamper_fails_closed():
    artifact = fit_prop_usage_v1(
        rows(), env(),
        source_receipts=receipt(),
        attempt9_artifact_sha256="b" * 64,
    )
    bad = copy.deepcopy(artifact)
    bad["markets"]["passing_yards"]["selected"]["decay"] = 0.123
    with pytest.raises(NflPropUsageV1FitError, match="ARTIFACT_SHA_MISMATCH"):
        validate_artifact(bad)
