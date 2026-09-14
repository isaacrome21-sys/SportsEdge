from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def parse_positions(value: str | list[str] | tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        parts = [str(x).strip().upper() for x in value]
    else:
        text = str(value or "").replace("/", ",")
        parts = [x.strip().upper() for x in text.split(",")]
    return tuple(dict.fromkeys(p for p in parts if p))


@dataclass(frozen=True)
class DKSlate:
    sport: str
    draft_group_id: int
    start_time: datetime
    name: str = ""
    game_count: int | None = None
    game_type_id: int | None = None
    contest_id: int | None = None
    contest_name: str = ""
    entry_fee: float | None = None
    total_prizes: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)


@dataclass(frozen=True)
class DKPlayer:
    player_id: str
    name: str
    team: str
    opponent: str
    positions: tuple[str, ...]
    salary: int
    game_id: str = ""
    game_start: datetime | None = None
    dk_fppg: float | None = None
    status: str = ""
    is_disabled: bool = False
    draftable_id: str = ""
    raw: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    def eligible_for(self, slot: str) -> bool:
        slot = slot.upper()
        pos = set(self.positions)
        if slot == "FLEX":
            return bool(pos & {"RB", "WR", "TE"})
        if slot == "SUPERFLEX":
            return bool(pos & {"QB", "RB", "WR", "TE"})
        if slot == "DST":
            return bool(pos & {"DST", "DEF"})
        return slot in pos


@dataclass(frozen=True)
class Projection:
    player_id: str
    mean: float
    ceiling: float
    floor: float = 0.0
    stddev: float | None = None
    ownership: float | None = None
    source: str = ""
    updated_at: datetime | None = None
    components: dict[str, float] = field(default_factory=dict, compare=False, repr=False)

    @property
    def upside(self) -> float:
        return max(0.0, self.ceiling - self.mean)
