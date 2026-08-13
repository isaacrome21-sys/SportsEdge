"""Pregame catcher identity and Baseball Savant catching context.

Catcher metrics are source-backed context only in V5.  They do not alter
GAME_SCORE_V5_STATCAST Model_P.  A separately validated V6 may consume them.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Mapping

from .mlb_source import MLBSourceError


@dataclass(frozen=True)
class CatcherContext:
    player_id: int
    name: str | None
    identity_basis: str
    framing: dict[str, Any] | None
    blocking: dict[str, Any] | None
    throwing: dict[str, Any] | None
    poptime: dict[str, Any] | None
    source: str = "BASEBALL_SAVANT_VIA_FUNGO_2_0_0"


def _pid(row: Mapping[str, Any]) -> int | None:
    for key in ("player_id", "id", "catcher_id"):
        try:
            value = int(row.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _find(rows: list[dict[str, Any]], player_id: int) -> dict[str, Any] | None:
    match = [dict(r) for r in rows if _pid(r) == int(player_id)]
    if len(match) > 1:
        raise MLBSourceError("CATCHER_METRIC_IDENTITY_AMBIGUOUS")
    return match[0] if match else None


def catcher_from_confirmed_box(box: Mapping[str, Any], side: str) -> tuple[int, str | None]:
    team = ((box.get("teams") or {}).get(side) or {})
    players = team.get("players") or {}
    found: list[tuple[int, str | None]] = []
    for row in players.values():
        order = row.get("battingOrder")
        if order is None:
            continue
        try:
            code = int(order)
        except (TypeError, ValueError):
            continue
        if code <= 0 or code % 100 != 0:
            continue
        positions = [row.get("position") or {}, *((row.get("allPositions") or []))]
        if not any(str(p.get("abbreviation") or "").upper() == "C" for p in positions if isinstance(p, Mapping)):
            continue
        person = row.get("person") or {}
        try:
            pid = int(person.get("id"))
        except (TypeError, ValueError):
            continue
        if pid > 0:
            found.append((pid, str(person.get("fullName") or "").strip() or None))
    unique = {pid: name for pid, name in found}
    if len(unique) != 1:
        raise MLBSourceError("CONFIRMED_STARTING_CATCHER_UNRESOLVED")
    pid = next(iter(unique))
    return pid, unique[pid]


def load_savant_catcher_boards(year: int) -> dict[str, list[dict[str, Any]]]:
    from fungo import statcast
    return {
        "framing": statcast.get_catcher_framing(year=year),
        "blocking": statcast.get_catcher_blocking(year=year),
        "throwing": statcast.get_catcher_throwing(year=year),
        "poptime": statcast.get_poptime(year=year),
    }


def build_catcher_context(player_id: int, name: str | None, basis: str, boards: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    out = CatcherContext(
        player_id=int(player_id), name=name, identity_basis=basis,
        framing=_find(list(boards.get("framing") or []), player_id),
        blocking=_find(list(boards.get("blocking") or []), player_id),
        throwing=_find(list(boards.get("throwing") or []), player_id),
        poptime=_find(list(boards.get("poptime") or []), player_id),
    )
    return asdict(out)
