"""Independent RED input-integrity battery against #2338 at 6a955293.

Test only: do not change the research engine or any pricing/governance code.
These are adversarial source-identity, historical-game and stat-support guards.
The original candidate is expected to return a research distribution from the
bad input rather than raise a named NflKickingError. Such failures are evidence;
they are not candidates for assertion weakening or a premature merge.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_kicking_empirical import (
    NflKickingError, build_kicking_games, estimate_kicking,
)

BASE = datetime(2026, 8, 1, 17, tzinfo=timezone.utc)
TARGET = datetime(2026, 10, 15, 18, tzinfo=timezone.utc)


def _game(i, *, kid="K1", game_id=None, attempts=None, pat_att=2, pat_made=2):
    return {
        "game_id": game_id or f"2026_GAME_{i}",
        "kicker_id": kid,
        "kickoff": BASE + timedelta(days=7 * i),
        "fg_attempts": [(36.0, True), (49.0, False)] if attempts is None else attempts,
        "pat_attempts": pat_att,
        "pat_makes": pat_made,
    }


def _valid_games():
    return [_game(i) for i in range(6)]


def test_positive_same_kicker_history_is_accepted():
    result = estimate_kicking(_valid_games(), kicker_id="K1", kickoff=TARGET)
    assert result["validation_status"] == "NOT_VALIDATED"
    assert result["games_used"] == 6
    assert all(
        all(p >= 0 for p in result[f]["pmf"].values())
        for f in ("fg_made", "xp_made", "kicking_points")
    )


def _named_refusal(rows, reason):
    with pytest.raises(NflKickingError, match=reason):
        estimate_kicking(rows, kicker_id="K1", kickoff=TARGET)


def test_foreign_kicker_history_cannot_enter_requested_kicker_distribution():
    """Wrong-ID kicks are not evidence about K1, even if dates are prior."""
    mixed = _valid_games() + [
        _game(6 + i, kid="K2", attempts=[(21, True)] * 5, pat_att=5, pat_made=5)
        for i in range(3)
    ]
    _named_refusal(mixed, "KICKING_HISTORY_PLAYER_MISMATCH")


def test_missing_kicker_identity_on_history_row_must_refuse():
    rows = _valid_games()
    del rows[0]["kicker_id"]
    _named_refusal(rows, "KICKING_HISTORY_PLAYER_MISMATCH")


def test_duplicate_game_id_cannot_count_as_independent_kicker_games():
    """One historical event cannot be counted twice toward MIN_GAMES."""
    rows = _valid_games()
    rows[5]["game_id"] = rows[4]["game_id"]
    _named_refusal(rows, "KICKING_HISTORY_DUPLICATE_GAME")


@pytest.mark.parametrize("pat_att,pat_made", [
    (1, 8),       # impossible made count, previously distorted p_pat
    (0, 1),       # a made PAT without an attempt
    (-1, 0),      # negative opportunities
])
def test_pat_makes_and_attempts_must_obey_count_support(pat_att, pat_made):
    rows = _valid_games()
    for row in rows:
        row["pat_attempts"] = pat_att
        row["pat_makes"] = pat_made
    _named_refusal(rows, "KICKING_PAT_SUPPORT_INVALID")


@pytest.mark.parametrize("distance", [None, float("nan"), -3.0])
def test_source_does_not_fabricate_or_rebucket_missing_fg_distance(distance):
    """Unknown/invalid distance must not become a zero-yard or 60+ attempt."""
    pd = pytest.importorskip("pandas")
    pbp = pd.DataFrame([{
        "game_id": "2026_01_A_B", "kicker_player_id": "K1",
        "kicker_player_name": "Kick One", "posteam": "A",
        "field_goal_attempt": 1, "field_goal_result": "made",
        "kick_distance": distance,
        "extra_point_attempt": 0, "extra_point_result": None,
    }])
    games = pd.DataFrame([{
        "game_id": "2026_01_A_B",
        "gameday": "2026-09-13", "gametime": "13:00",
    }])
    with pytest.raises(NflKickingError, match="KICKING_FG_DISTANCE_INVALID"):
        build_kicking_games(pbp, games)


def test_positive_source_preserves_measured_fg_distance():
    pd = pytest.importorskip("pandas")
    pbp = pd.DataFrame([{
        "game_id": "2026_01_A_B", "kicker_player_id": "K1",
        "kicker_player_name": "Kick One", "posteam": "A",
        "field_goal_attempt": 1, "field_goal_result": "made",
        "kick_distance": 43.0,
        "extra_point_attempt": 0, "extra_point_result": None,
    }])
    games = pd.DataFrame([{
        "game_id": "2026_01_A_B",
        "gameday": "2026-09-13", "gametime": "13:00",
    }])
    records = build_kicking_games(pbp, games)
    assert len(records) == 1
    assert records[0]["kicker_id"] == "K1"
    assert records[0]["fg_attempts"] == [(43.0, True)]
