"""Keep the intake schedule snapshot down to the bound game_pk."""
from __future__ import annotations

from typing import Iterable

from .mlb_source import GameSnapshot


def filter_schedule_to_game_pk(
    schedule: Iterable[GameSnapshot] | None,
    game_pk: int | str | None,
) -> list[GameSnapshot]:
    if schedule is None or game_pk in (None, ""):
        return []
    want = str(game_pk)
    return [game for game in schedule if str(game.game_pk) == want]
