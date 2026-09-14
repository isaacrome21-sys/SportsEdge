from __future__ import annotations

from sportsedge.dfs.mlb_pitcher_contract import normalize_starter_path
from sportsedge.dfs.mlb_starter_paths import build_game_starter_path_component


def _starter_row(
    *,
    outs: int = 18,
    runs: int = 1,
    earned_runs: int = 1,
    complete_game: int = 0,
) -> dict[str, float]:
    return {
        "outs": float(outs),
        "strikeouts": 6.0,
        "earned_runs": float(earned_runs),
        "runs_allowed": float(runs),
        "hits_allowed": 4.0,
        "walks_allowed": 2.0,
        "hbp_allowed": 0.0,
        "starter_exit_batters_faced": 24.0,
        "starter_exit_pitch_count": 91.0,
        "complete_game_probability": float(complete_game),
        "cg_shutout_probability": 0.0,
        "no_hitter_probability": 0.0,
    }


def _features(
    source_hash: str,
    *,
    starter_row: dict[str, float] | None = None,
    required_outs: int | None = 15,
) -> dict[str, object]:
    row = starter_row or _starter_row()
    return {
        "feature_source_hash": source_hash,
        "starter_history": [dict(row) for _ in range(5)],
        "credit_history": [
            {
                "team_won": True,
                "win_credit_required_outs": required_outs,
            }
            for _ in range(10)
        ],
    }


def _build(
    *,
    away_features: dict[str, object] | None = None,
    home_features: dict[str, object] | None = None,
    pmf: dict[str, float] | None = None,
):
    return build_game_starter_path_component(
        away_player_id="away-sp",
        home_player_id="home-sp",
        away_features=away_features or _features("a" * 64),
        home_features=home_features or _features("b" * 64),
        joint_score_pmf=pmf or {"4,2": 1.0},
        simulations=1000,
        build_hash="c" * 64,
    )


def test_paths_are_deterministic_aligned_and_carry_exit_state() -> None:
    first = _build()
    second = _build()
    assert first == second
    assert first["path_count"] == 1000
    assert len(first["players"]) == 2
    assert first["players"][0]["path_set_id"] == first["path_set_id"]
    assert first["players"][1]["path_set_id"] == first["path_set_id"]
    for player in first["players"]:
        assert len(player["samples"]) == 1000
        sample = player["samples"][0]
        assert sample["starter_exit_batters_faced"] == 24.0
        assert sample["starter_exit_pitch_count"] == 91.0
        assert sample["starter_scoped_events"] == 1.0


def test_only_one_probable_starter_can_receive_win_credit_per_path() -> None:
    result = _build(pmf={"4,2": 0.5, "2,4": 0.5})
    away = result["players"][0]["samples"]
    home = result["players"][1]["samples"]
    assert all(a["win_probability"] + h["win_probability"] <= 1.0 for a, h in zip(away, home))
    assert any(a["win_probability"] == 1.0 for a in away)
    assert any(h["win_probability"] == 1.0 for h in home)


def test_team_win_does_not_credit_starter_before_five_innings() -> None:
    short = _features("a" * 64, starter_row=_starter_row(outs=14))
    result = _build(away_features=short, pmf={"4,2": 1.0})
    away = result["players"][0]["samples"]
    assert all(sample["team_final_runs"] == 4.0 for sample in away)
    assert all(sample["win_probability"] == 0.0 for sample in away)


def test_permanent_lead_before_qualified_exit_credits_win() -> None:
    result = _build(pmf={"4,2": 1.0})
    away = result["players"][0]["samples"]
    assert all(sample["lead_at_exit"] == 1.0 for sample in away)
    assert all(sample["lead_preserved_to_final"] == 1.0 for sample in away)
    assert all(sample["win_probability"] == 1.0 for sample in away)


def test_final_team_win_without_proven_credit_path_does_not_invent_win() -> None:
    no_credit = _features("a" * 64, required_outs=None)
    result = _build(away_features=no_credit, pmf={"4,2": 1.0})
    away = result["players"][0]["samples"]
    assert all(sample["lead_at_exit"] == 0.0 for sample in away)
    assert all(sample["lead_preserved_to_final"] == 0.0 for sample in away)
    assert all(sample["win_probability"] == 0.0 for sample in away)


def test_bullpen_damage_stays_out_of_starter_line() -> None:
    starter = _features("a" * 64, starter_row=_starter_row(runs=1, earned_runs=1))
    result = _build(away_features=starter, pmf={"6,4": 1.0})
    away = result["players"][0]["samples"]
    assert all(sample["runs_allowed"] == 1.0 for sample in away)
    assert all(sample["earned_runs"] == 1.0 for sample in away)
    assert all(sample["opponent_final_runs"] == 4.0 for sample in away)
    assert all(sample["bullpen_runs_allowed"] == 3.0 for sample in away)


def test_complete_game_row_must_own_all_opponent_runs() -> None:
    cg = _features(
        "a" * 64,
        starter_row=_starter_row(outs=27, runs=2, earned_runs=2, complete_game=1),
    )
    result = _build(away_features=cg, pmf={"4,2": 1.0})
    away = result["players"][0]["samples"]
    assert all(sample["bullpen_runs_allowed"] == 0.0 for sample in away)


def test_four_strikeout_inning_is_legal_when_bf_supports_it() -> None:
    normalized = normalize_starter_path(
        {
            "outs": 3.0,
            "strikeouts": 4.0,
            "earned_runs": 0.0,
            "hits_allowed": 1.0,
            "walks_allowed": 0.0,
            "hbp_allowed": 0.0,
            "starter_exit_batters_faced": 5.0,
            "starter_exit_pitch_count": 24.0,
            "starter_scoped_events": 1.0,
            "lead_at_exit": 0.0,
            "lead_preserved_to_final": 0.0,
        }
    )
    assert normalized["strikeouts"] == 4.0
