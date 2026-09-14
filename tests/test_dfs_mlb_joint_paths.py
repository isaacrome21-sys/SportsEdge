from __future__ import annotations

from datetime import datetime, timezone
import json

from sportsedge.dfs.mlb_joint_paths import (
    BaserunningProfile,
    HitterPathInput,
    HookHazardSurface,
    MlbGamePathInput,
    PlateAppearanceProfile,
    TeamPathInput,
    simulate_mlb_joint_paths,
)
from sportsedge.dfs.score_paths import load_aligned_score_paths
from sportsedge.dfs.types import DKPlayer


def _profile(source: str, *, pitches: int = 4) -> PlateAppearanceProfile:
    return PlateAppearanceProfile(
        outcome_probabilities={
            "OUT": 0.55,
            "K": 0.15,
            "1B": 0.13,
            "2B": 0.05,
            "HR": 0.05,
            "BB": 0.05,
            "HBP": 0.02,
        },
        pitch_count_probabilities={pitches: 1.0},
        source_id=source,
    )


def _hook(source: str) -> HookHazardSurface:
    return HookHazardSurface(
        pitch_count_upper_bounds=(50, 75, 100, 220),
        runs_allowed_upper_bounds=(0, 2, 5, 25),
        remove_probabilities=(
            (0.00, 0.03, 0.30, 1.00),
            (0.03, 0.15, 0.65, 1.00),
            (0.30, 0.65, 0.95, 1.00),
            (0.98, 1.00, 1.00, 1.00),
        ),
        source_id=source,
    )


def _team(prefix: str, *, pitches: int = 4) -> TeamPathInput:
    return TeamPathInput(
        team=prefix,
        lineup=tuple(
            HitterPathInput(
                player_id=f"{prefix}-H{i}",
                starter_profile=_profile(f"{prefix}-starter-{i}", pitches=pitches),
                bullpen_profile=_profile(f"{prefix}-bullpen-{i}", pitches=4),
            )
            for i in range(1, 10)
        ),
        starter_player_id=f"{prefix}-P",
        hook_surface=_hook(f"{prefix}-hook"),
    )


def _game(*, away_pitches: int = 4, home_pitches: int = 4) -> MlbGamePathInput:
    return MlbGamePathInput(
        game_id="game-1",
        away=_team("AWY", pitches=away_pitches),
        home=_team("HME", pitches=home_pitches),
        baserunning=BaserunningProfile(
            single_second_scores=0.58,
            single_first_to_third=0.27,
            double_first_scores=0.46,
            source_id="test-baserunning",
        ),
        updated_at=datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc),
        source_id="test-fixture-v1",
    )


def _players(game: MlbGamePathInput) -> list[DKPlayer]:
    players: list[DKPlayer] = []
    for team in (game.away, game.home):
        opponent = game.home.team if team is game.away else game.away.team
        for index, hitter in enumerate(team.lineup):
            positions = ("C",) if index == 0 else ("OF",)
            players.append(
                DKPlayer(
                    player_id=hitter.player_id,
                    name=hitter.player_id,
                    team=team.team,
                    opponent=opponent,
                    positions=positions,
                    salary=4000,
                )
            )
        players.append(
            DKPlayer(
                player_id=team.starter_player_id,
                name=team.starter_player_id,
                team=team.team,
                opponent=opponent,
                positions=("P",),
                salary=9000,
            )
        )
    return players


def _row(snapshot: dict[str, object], player_id: str) -> dict[str, object]:
    rows = snapshot["players"]
    assert isinstance(rows, list)
    for row in rows:
        if isinstance(row, dict) and row.get("player_id") == player_id:
            return row
    raise AssertionError(player_id)


def test_path_set_is_deterministic_and_seed_bound() -> None:
    game = _game()
    first = simulate_mlb_joint_paths(game, path_count=40, seed=17)
    second = simulate_mlb_joint_paths(game, path_count=40, seed=17)
    third = simulate_mlb_joint_paths(game, path_count=40, seed=18)
    assert first.path_set_id == second.path_set_id
    assert first.snapshot == second.snapshot
    assert first.path_set_id != third.path_set_id


def test_every_pitcher_path_satisfies_v3_conservation_and_no_double_win() -> None:
    result = simulate_mlb_joint_paths(_game(), path_count=120, seed=91)
    away = _row(result.snapshot, "AWY-P")["samples"]
    home = _row(result.snapshot, "HME-P")["samples"]
    assert isinstance(away, list) and isinstance(home, list)
    for away_sample, home_sample in zip(away, home, strict=True):
        assert away_sample["hits_allowed"] + away_sample["bullpen_hits_allowed"] == away_sample["opponent_team_hits"]
        assert home_sample["hits_allowed"] + home_sample["bullpen_hits_allowed"] == home_sample["opponent_team_hits"]
        assert away_sample["hook_endogenous_to_path"] == 1.0
        assert home_sample["hook_decision_batter_by_batter"] == 1.0
        assert away_sample["game_simulated_to_final"] == 1.0
        assert away_sample["win_probability"] + home_sample["win_probability"] <= 1.0
        if away_sample["win_probability"]:
            assert away_sample["outs"] >= 15.0
            assert away_sample["lead_at_exit"] == 1.0
            assert away_sample["lead_preserved_to_final"] == 1.0


def test_hook_surface_is_conditioned_on_pitch_count_and_runs_allowed() -> None:
    hook = _hook("conditioned")
    assert hook.removal_probability(pitch_count=40, runs_allowed=0) == 0.0
    assert hook.removal_probability(pitch_count=80, runs_allowed=0) == 0.30
    assert hook.removal_probability(pitch_count=40, runs_allowed=5) == 0.30
    assert hook.removal_probability(pitch_count=80, runs_allowed=5) == 0.95


def test_more_pitches_per_pa_shortens_starter_workload_under_same_hook_surface() -> None:
    slow = simulate_mlb_joint_paths(_game(home_pitches=2), path_count=200, seed=11)
    long = simulate_mlb_joint_paths(_game(home_pitches=8), path_count=200, seed=11)
    slow_samples = _row(slow.snapshot, "AWY-P")["samples"]
    long_samples = _row(long.snapshot, "AWY-P")["samples"]
    assert isinstance(slow_samples, list) and isinstance(long_samples, list)
    slow_bf = sum(sample["starter_exit_batters_faced"] for sample in slow_samples) / len(slow_samples)
    long_bf = sum(sample["starter_exit_batters_faced"] for sample in long_samples) / len(long_samples)
    assert long_bf < slow_bf


def test_snapshot_is_directly_consumable_as_aligned_dk_score_paths(tmp_path) -> None:
    game = _game()
    result = simulate_mlb_joint_paths(game, path_count=1000, seed=404)
    path = tmp_path / "mlb_paths.json"
    path.write_text(json.dumps(result.snapshot), encoding="utf-8")
    loaded = load_aligned_score_paths(path, _players(game), "MLB")
    assert loaded.path_set_id == result.path_set_id
    assert loaded.path_count == 1000
    assert len(loaded.player_scores) == 20
    assert all(len(scores) == 1000 for scores in loaded.player_scores.values())
