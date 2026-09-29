from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nba.public_history import PublicNBABoxGame, materialize_public_training_rows

UTC = timezone.utc


def _game(i, home, away, day, *, observed_delay_hours=3, hp=110, ap=104):
    tip = datetime(2026, 1, day, 1, 0, tzinfo=UTC)
    return PublicNBABoxGame(
        game_id=f"g{i}", tipoff=tip, observed_at=tip + timedelta(hours=observed_delay_hours),
        home_team_id=home, away_team_id=away, home_points=hp, away_points=ap,
        home_fga=88, home_fta=20, home_orb=10, home_turnovers=12,
        away_fga=86, away_fta=18, away_orb=9, away_turnovers=13,
        source_uri="https://github.com/sportsdataverse/hoopR-nba-data",
        source_version=f"commit-{i}",
    )


def test_materializes_only_from_prior_published_games():
    games = [
        _game(1, "A", "C", 1), _game(2, "B", "D", 2),
        _game(3, "A", "D", 3), _game(4, "B", "C", 4),
        _game(5, "A", "C", 5), _game(6, "B", "D", 6),
        _game(7, "A", "B", 7, hp=115, ap=111),
    ]
    rows = materialize_public_training_rows(games, window=3, min_history=3)
    target = next(r for r in rows if r.game_id == "g7")
    assert target.feature_as_of < target.tipoff
    assert target.home_team_id == "A"
    assert target.away_team_id == "B"
    assert target.home_points == 115 and target.away_points == 111
    assert target.source_version.startswith("PUBLIC_REPO_ROLLING_V1:")


def test_late_backfill_cannot_enter_earlier_target_features():
    games = [
        _game(1, "A", "C", 1), _game(2, "B", "D", 2),
        _game(3, "A", "D", 3), _game(4, "B", "C", 4),
        _game(5, "A", "C", 5, observed_delay_hours=80),
        _game(6, "B", "D", 6), _game(7, "A", "B", 7),
    ]
    rows = materialize_public_training_rows(games, window=3, min_history=2)
    target = next(r for r in rows if r.game_id == "g7")
    # g5 is published after g7 tipoff, so the latest used observation must predate g7.
    assert target.feature_as_of < target.tipoff


def test_rejects_non_final_or_unproven_observation_time():
    game = _game(1, "A", "B", 1)
    bad = PublicNBABoxGame(**{**game.__dict__, "observed_at": game.tipoff})
    with pytest.raises(ValueError, match="after tipoff"):
        materialize_public_training_rows([bad])


def test_requires_https_provenance():
    game = _game(1, "A", "B", 1)
    bad = PublicNBABoxGame(**{**game.__dict__, "source_uri": "file://nba.csv"})
    with pytest.raises(ValueError, match="https"):
        materialize_public_training_rows([bad])
