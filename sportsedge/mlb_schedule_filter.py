"""Keep the schedule snapshot down to the game the phone row already bound."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from .mlb_source import GameSnapshot, parse_game_start


def filter_schedule_to_first_pitch(
    schedule: Iterable[GameSnapshot] | None,
    first_pitch_at: datetime | str | None,
    *,
    tolerance_seconds: float = 120.0,
) -> list[GameSnapshot] | None:
    if schedule is None:
        return None
    games = list(schedule)
    if first_pitch_at in (None, ""):
        return games
    if isinstance(first_pitch_at, str):
        first_pitch_at = datetime.fromisoformat(first_pitch_at.replace("Z", "+00:00"))
    target = first_pitch_at.astimezone(timezone.utc)
    matched = [
        game for game in games
        if abs((parse_game_start(game.game_date) - target).total_seconds()) <= tolerance_seconds
    ]
    return matched
