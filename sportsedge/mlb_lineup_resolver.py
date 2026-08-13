"""Resolve a complete 1-9 batting order from official MLB evidence."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .mlb_lineup_projection import ProjectedLineup
from .mlb_source import MLBSourceError, parse_confirmed_lineup


@dataclass(frozen=True)
class ResolvedMLBLineup:
    player_ids: tuple[int, ...]
    basis: str
    source_game_pks: tuple[int, ...] = ()

    def top3(self) -> tuple[int, int, int]:
        if len(self.player_ids) != 9 or len(set(self.player_ids)) != 9:
            raise MLBSourceError("RESOLVED_LINEUP_NOT_COMPLETE")
        return self.player_ids[0], self.player_ids[1], self.player_ids[2]


def confirmed_nine(box: Mapping[str, Any], side: str) -> tuple[int, ...]:
    slots: dict[int, int] = {}
    for row in parse_confirmed_lineup(dict(box), side):
        try:
            slot = int(row.get("slot")); sequence = int(row.get("sequence", 0)); pid = int(row.get("player_id"))
        except (TypeError, ValueError):
            continue
        if sequence == 0 and 1 <= slot <= 9 and pid > 0:
            slots[slot] = pid
    if set(slots) != set(range(1, 10)) or len(set(slots.values())) != 9:
        raise MLBSourceError("CONFIRMED_LINEUP_NOT_COMPLETE")
    return tuple(slots[s] for s in range(1, 10))


def resolve_mlb_lineup(box: Mapping[str, Any], side: str, team_id: int, mlb_projected: Mapping[int, ProjectedLineup]) -> ResolvedMLBLineup:
    try:
        return ResolvedMLBLineup(confirmed_nine(box, side), "CONFIRMED_MLB")
    except Exception as confirmed_exc:
        projected = mlb_projected.get(int(team_id))
        if projected is None:
            raise MLBSourceError(f"LINEUP_UNRESOLVED:{side}:{confirmed_exc}") from confirmed_exc
        ids = tuple(int(x) for x in projected.player_ids)
        if tuple(projected.batting_slots) != tuple(range(1, 10)) or len(ids) != 9 or len(set(ids)) != 9:
            raise MLBSourceError("MLB_PROJECTED_LINEUP_NOT_COMPLETE")
        return ResolvedMLBLineup(ids, "PROJECTED_MLB_PRIOR_CONFIRMED", tuple(int(x) for x in projected.source_game_pks))
