"""Bind phone matchups to the earliest game that has not started."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .mlb_lines_intake import LinesIntakeError, _match_team, parse_lines
from .mlb_source import GameSnapshot, parse_game_start

ROW_BINDS = ("AMBIGUOUS_GAME", "GAME_NOT_PREGAME")


def resolve_game(away: str, home: str, schedule: list[GameSnapshot], *, now: datetime) -> GameSnapshot:
    hits = [
        game for game in schedule
        if game.away_name in _match_team(away, [game.away_name])
        and game.home_name in _match_team(home, [game.home_name])
    ]
    if not hits:
        raise LinesIntakeError(f"GAME_NOT_FOUND: '{away} @ {home}' matched 0 games on this slate")
    future = [game for game in hits if parse_game_start(game.game_date) > now]
    future.sort(key=lambda game: parse_game_start(game.game_date))
    if len(future) == 1:
        return future[0]
    if len(future) > 1:
        raise LinesIntakeError(f"AMBIGUOUS_GAME: '{away} @ {home}' matched {len(future)} pregame starts")
    raise LinesIntakeError(f"GAME_NOT_PREGAME: '{away} @ {home}'")


def _unbound_row(row, *, observed_at: str, book: str, reason: str) -> dict[str, Any]:
    return {
        "game_id": f"{row.away}@{row.home}",
        "market_type": row.market_type,
        "side": row.side,
        "line": row.line,
        "price": row.price,
        "paired_side": row.paired_side,
        "paired_price": row.paired_price,
        "book": book,
        "observed_at": observed_at,
        "first_pitch_at": None,
        "source": "MANUAL",
        "timestamp_source": "INTAKE_STAMPED",
        "bind_status": reason,
    }


def build_bound_input(
    text: str,
    *,
    observed_at: str,
    schedule: list[GameSnapshot],
    book: str = "draftkings",
) -> dict[str, Any]:
    now = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    out: list[dict[str, Any]] = []
    for row in parse_lines(text):
        try:
            game = resolve_game(row.away, row.home, schedule, now=now)
        except LinesIntakeError as exc:
            reason = str(exc).split(":", 1)[0]
            if reason not in ROW_BINDS:
                raise
            out.append(_unbound_row(row, observed_at=observed_at, book=book, reason=reason))
            continue
        out.append({
            "game_id": f"{game.away_name}@{game.home_name}",
            "market_type": row.market_type,
            "side": row.side,
            "line": row.line,
            "price": row.price,
            "paired_side": row.paired_side,
            "paired_price": row.paired_price,
            "book": book,
            "observed_at": observed_at,
            "first_pitch_at": parse_game_start(game.game_date).isoformat(),
            "source": "MANUAL",
            "timestamp_source": "INTAKE_STAMPED",
        })
    return {"rows": out}
