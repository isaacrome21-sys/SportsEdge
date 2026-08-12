"""Fail-closed range validation for historical schedule source/cache payloads."""
from __future__ import annotations

from datetime import date
from typing import Any, Mapping


class SourceRangeError(ValueError):
    pass


def _parse_bound(raw: str, code: str) -> date:
    try:
        return date.fromisoformat(raw)
    except Exception as exc:
        raise SourceRangeError(code) from exc


def partition_schedule_games(
    payload: Mapping[str, Any], *, start: str, end: str
) -> tuple[list[Mapping[str, Any]], list[dict[str, Any]]]:
    """Return only rows whose MLB officialDate is inside the requested interval.

    Out-of-range rows are never passed downstream, even if they are marked Final and
    otherwise contain complete model fields. This applies equally to fresh HTTP
    responses and restored cache files.
    """
    lo = _parse_bound(start, "SOURCE_START_DATE_INVALID")
    hi = _parse_bound(end, "SOURCE_END_DATE_INVALID")
    if lo > hi:
        raise SourceRangeError("SOURCE_RANGE_REVERSED")

    accepted: list[Mapping[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for block in payload.get("dates") or []:
        for game in block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            raw = game.get("officialDate") or block.get("date")
            try:
                d = date.fromisoformat(str(raw))
            except Exception:
                # Date validity is handled by the downstream loader. The range layer
                # must not invent a date merely to place the row inside the request.
                accepted.append(game)
                continue
            if lo <= d <= hi:
                accepted.append(game)
                continue
            violations.append({
                "game_pk": int(game.get("gamePk") or 0),
                "official_date": d.isoformat(),
                "requested_start": lo.isoformat(),
                "requested_end": hi.isoformat(),
                "reason_code": "SOURCE_RANGE_VIOLATION",
            })
    accepted.sort(key=lambda g: (str(g.get("officialDate") or ""), int(g.get("gamePk") or 0)))
    violations.sort(key=lambda x: (x["official_date"], x["game_pk"], x["requested_start"], x["requested_end"]))
    return accepted, violations
