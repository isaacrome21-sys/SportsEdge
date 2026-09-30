"""Card notes for rows the live gate refused."""
from __future__ import annotations

from typing import Any


def blocked_notes(payload: dict[str, Any]) -> list[str]:
    notes: list[str] = []
    blocked = payload.get("blocked") or []
    for item in blocked:
        if isinstance(item, dict):
            notes.append(f"BLOCKED {item.get('game_id')}: {item.get('reason')}")
    if blocked and not (payload.get("results") or payload.get("games")):
        notes.append("ALL_BLOCKED: no priced rows. This is not a pass.")
    return notes
