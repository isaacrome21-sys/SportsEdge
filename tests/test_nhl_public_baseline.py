from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sportsedge.sports.nhl.official_boxscore_source import NHLOfficialCompletedGame
from sportsedge.sports.nhl.public_baseline import (
    BASELINE_FEATURES,
    artifact_from_json_dict,
    build_baseline_matchup,
    build_baseline_training_rows,
    fit_public_baseline,
    game_state_from_public_baseline,
)


def _game(index: int, *, home_reg: int | None = None, away_reg: int | None = None) -> NHLOfficialCompletedGame:
    start = datetime(2025, 10, 1, 23, 0, tzinfo=timezone.utc) + timedelta(days=index * 2)
    home_is_a = index % 2 == 0
    home_id, away_id = ("A", "B") if home_is_a else ("B", "A")
    home_abbrev, away_abbrev = ("AAA", "BBB") if home_is_a else ("BBB", "AAA")
    hg = (3 + (index % 3 == 0)) if home_reg is None else home_reg
    ag = (2 + (index % 4 == 0)) if away_reg is None else away_reg
    return NHLOfficialCompletedGame(
        game_id=f"202502{index:04d}",
        season="20252026",
        game_type=2,
        game_date=start.date().isoformat(),
        start_time_utc=start.isoformat(),
        captured_at=(start + timedelta(hours=4)).isoformat(),
        game_state="OFF",
        away_team_id=away_id,
        home_team_id=home_id,
        away_abbrev=away_abbrev,
        home_abbrev=home_abbrev,
        away_regulation_goals=ag,
        home_regulation_goals=hg,
        away_final_goals=ag,
        home_final_goals=hg,
        away_sog=27 + index % 5,
        home_sog=31 + index % 6,
        away_pp_goals=1 if index % 3 else 0,
        away_pp_opportunities=3,
        home_pp_goals=1 if index % 4 else 2,
        home_pp_opportunities=4,
        away_goalies=(),
        home_goalies=(),
        source_uri=f"https://api-web.nhle.com/v1/gamecenter/202502{index:04d}/boxscore",
        source_raw_sha256=f"{index % 16:x}" * 64,
        source_version="fixture-v1",
    )


def _history(n: int = 24) -> list[NHLOfficialCompletedGame]:
    return [_game(i) for i in range(n)]


def test_training_rows_use_prior_games_only():
    games = _history()
    rows = build_baseline_training_rows(games, min_team_games=3)
    assert len(rows) == (len(games) - 3) * 2
    assert all(len(row.features) == len(BASELINE_FEATURES) for row in rows)

    changed = list(games)
    changed[-1] = _game(len(games) - 1, home_reg=12, away_reg=0)
    changed_rows = build_baseline_training_rows(changed, min_team_games=3)

    # Changing the target result of the final game must not change any feature
    # vector, including that final game's own pregame feature vector.
    assert [row.features for row in rows] == [row.features for row in changed_rows]
    assert [row.regulation_goals for row in rows[:-2]] == [row.regulation_goals for row in changed_rows[:-2]]
    assert [row.regulation_goals for row in rows[-2:]] != [row.regulation_goals for row in changed_rows[-2:]]


def test_future_game_cannot_leak_into_matchup_features():
    games = _history(16)
    last_start = datetime.fromisoformat(games[-1].start_time_utc)
    puck = last_start + timedelta(days=2)
    base = build_baseline_matchup(
        games, game_id="future", home_team_id="A", away_team_id="B",
        puck_drop=puck.isoformat(), min_team_games=3,
    )

    future = _game(100, home_reg=15, away_reg=0)
    with_future = build_baseline_matchup(
        [*games, future], game_id="future", home_team_id="A", away_team_id="B",
        puck_drop=puck.isoformat(), min_team_games=3,
    )
    assert with_future.home_features == base.home_features
    assert with_future.away_features == base.away_features
    assert with_future.latest_history_start == base.latest_history_start


def test_fit_is_deterministic_market_blind_and_produces_positive_goal_rates():
    rows = build_baseline_training_rows(_history(30), min_team_games=3)
    artifact = fit_public_baseline(rows, version="nhl-public-boxscore-baseline-v1", ridge=1.0)
    artifact2 = fit_public_baseline(reversed(rows), version="nhl-public-boxscore-baseline-v1", ridge=1.0)
    assert artifact.training_sha256 == artifact2.training_sha256
    assert artifact.training_rows == len(rows)
    assert artifact.feature_names == BASELINE_FEATURES
    assert "NOT Model_P" in artifact.authority

    restored = artifact_from_json_dict(artifact.as_json_dict())
    assert restored == artifact

    games = _history(30)
    puck = datetime.fromisoformat(games[-1].start_time_utc) + timedelta(days=2)
    matchup = build_baseline_matchup(
        games, game_id="2026029999", home_team_id="A", away_team_id="B",
        puck_drop=puck.isoformat(), min_team_games=3,
    )
    state = game_state_from_public_baseline(matchup, artifact)
    assert state.home_regulation_goals > 0
    assert state.away_regulation_goals > 0
    assert state.game_id == "2026029999"
