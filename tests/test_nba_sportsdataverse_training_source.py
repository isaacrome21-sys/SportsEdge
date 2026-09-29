from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.sports.nba.sportsdataverse_training_source import build_training_rows_from_team_boxes


def _game(i, home="A", away="B", *, known_delay_hours=3):
    tip = datetime(2025, 1, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
    base = dict(
        game_id=f"g{i}", game_date_time=tip.isoformat(),
        known_at=(tip + timedelta(hours=known_delay_hours)).isoformat(),
        field_goals_attempted=90, offensive_rebounds=10, turnovers=12,
        free_throws_attempted=20,
    )
    return [
        dict(base, team_id=home, team_home_away="home", team_score=110 + i % 3),
        dict(base, team_id=away, team_home_away="away", team_score=105 + i % 2),
    ]


def test_materializes_only_from_prior_known_finals():
    rows = []
    for i in range(8):
        rows.extend(_game(i))
    out = build_training_rows_from_team_boxes(rows, source_version="sd-test", minimum_history_games=3, rolling_games=5)
    assert len(out) == 5
    first = out[0]
    assert first.game_id == "g3"
    assert first.feature_as_of < first.tipoff
    assert first.home_points == 110
    assert first.expected_possessions > 0
    assert first.home_offensive_rating > 0
    assert first.home_defensive_rating > 0


def test_target_result_cannot_enter_its_features():
    rows = []
    for i in range(5):
        rows.extend(_game(i))
    base = build_training_rows_from_team_boxes(rows, source_version="sd-test", minimum_history_games=3)
    mutated = [dict(r) for r in rows]
    for row in mutated:
        if row["game_id"] == "g3" and row["team_home_away"] == "home":
            row["team_score"] = 180
    changed = build_training_rows_from_team_boxes(mutated, source_version="sd-test", minimum_history_games=3)
    b = next(r for r in base if r.game_id == "g3")
    c = next(r for r in changed if r.game_id == "g3")
    assert b.expected_possessions == c.expected_possessions
    assert b.home_offensive_rating == c.home_offensive_rating
    assert c.home_points == 180


def test_requires_row_level_known_at():
    rows = _game(0)
    del rows[0]["known_at"]
    with pytest.raises(ValueError, match="row-level known_at"):
        build_training_rows_from_team_boxes(rows, source_version="sd-test", minimum_history_games=1)


def test_rejects_market_fields_recursively():
    rows = _game(0)
    rows[0]["sportsbook_price"] = -110
    with pytest.raises(ValueError, match="market input forbidden"):
        build_training_rows_from_team_boxes(rows, source_version="sd-test", minimum_history_games=1)


def test_late_published_prior_game_is_not_used_early():
    rows = []
    rows.extend(_game(0))
    rows.extend(_game(1, known_delay_hours=30))
    rows.extend(_game(2))
    rows.extend(_game(3))
    out = build_training_rows_from_team_boxes(rows, source_version="sd-test", minimum_history_games=2)
    assert all(r.game_id != "g2" for r in out)
