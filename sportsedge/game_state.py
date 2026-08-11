"""Fail-closed game-state eligibility for pregame SportsEdge models."""
from __future__ import annotations

from typing import Any


class GameStateError(ValueError):
    pass


def require_mlb_pregame(game: Any) -> None:
    """Require MLB's canonical abstract game state to be Preview.

    Current SportsEdge markets are pregame models. Live, Final, missing, or any
    unrecognized state is ineligible rather than inferred from clock time or a
    detailed-status string.
    """
    state = getattr(game, "status", None)
    if state != "Preview":
        raise GameStateError("GAME_NOT_PREGAME")
