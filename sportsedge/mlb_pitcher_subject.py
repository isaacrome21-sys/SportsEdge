"""Resolve pitcher-prop names to the bound game's probable starters."""
from __future__ import annotations

import unicodedata
from typing import Any

from .mlb_source import GameSnapshot


def norm_person(value: str) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch.lower() for ch in folded if ch.isalnum() and not unicodedata.combining(ch))


def resolve_pitcher_subject(row: Any, game: GameSnapshot) -> tuple[str, int]:
    name = str(getattr(row, "subject_name", None) or "").strip()
    if not name:
        raise ValueError("SUBJECT_UNRESOLVED")
    target = norm_person(name)
    probable = [
        (game.away_probable_pitcher_id, game.away_probable_pitcher_name, game.away_id),
        (game.home_probable_pitcher_id, game.home_probable_pitcher_name, game.home_id),
    ]
    matches = [item for item in probable if item[0] and item[1] and norm_person(item[1]) == target]
    if len(matches) != 1:
        raise ValueError(f"SUBJECT_UNRESOLVED:{name}")
    person_id, _, team_id = matches[0]
    supplied = getattr(row, "subject_id", None)
    if supplied not in (None, "") and str(supplied) != str(person_id):
        raise ValueError(f"MANUAL_SUBJECT_ID_NAME_MISMATCH:{name}")
    return str(person_id), int(team_id)
