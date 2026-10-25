"""Parse phone NHL lines. Fail closed on one-sided rows."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any


class NhlLinesIntakeError(ValueError):
    pass


@dataclass
class NhlMarketLine:
    market: str
    line: float | None
    away_or_over_price: int
    home_or_under_price: int
    raw: str


@dataclass
class NhlGameTicket:
    away: str
    home: str
    header: str
    markets: list[NhlMarketLine] = field(default_factory=list)
    # When the prices were read off DraftKings (``Captured`` line). Never the
    # GitHub issue time.
    captured_at: str | None = None


CAPTURE_LINE_RE = re.compile(r"^captured\b\s*:?\s*(.*?)\s*$", re.I)


def _captured_at(token: str, raw: str) -> str:
    if not token or " " in token:
        raise NhlLinesIntakeError(f"NHL_INTAKE_CAPTURED_AT_INVALID:{raw}")
    try:
        value = datetime.fromisoformat(token.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise NhlLinesIntakeError(f"NHL_INTAKE_CAPTURED_AT_INVALID:{raw}") from exc
    if "T" not in token.upper() or value.utcoffset() is None:
        raise NhlLinesIntakeError(f"NHL_INTAKE_CAPTURED_AT_TZ_REQUIRED:{raw}")
    return value.isoformat()


def _american(token: str) -> int:
    try:
        number = Decimal(token.strip())
    except InvalidOperation as exc:
        raise NhlLinesIntakeError(f"NHL_INTAKE_ODDS_INVALID:{token}") from exc
    if (not number.is_finite() or not isfinite(float(number))
            or number != number.to_integral_value()
            or -100 < number < 100):
        raise NhlLinesIntakeError(f"NHL_INTAKE_ODDS_INVALID:{token}")
    return int(number)


def _line_value(token: str, raw: str) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise NhlLinesIntakeError(f"NHL_INTAKE_LINE_INVALID:{raw}") from exc
    if not isfinite(value):
        raise NhlLinesIntakeError(f"NHL_INTAKE_LINE_INVALID:{raw}")
    return value


def parse_nhl_lines(body: str) -> list[NhlGameTicket]:
    games: list[NhlGameTicket] = []
    current: NhlGameTicket | None = None
    board_captured: str | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("###"):
            continue
        if line.upper().startswith("[NHL LINES]") and not games:
            continue
        capture = CAPTURE_LINE_RE.match(line)
        if capture:
            value = _captured_at(capture.group(1), line)
            if current is None:
                if board_captured is not None:
                    raise NhlLinesIntakeError("NHL_INTAKE_CAPTURED_AT_DUPLICATE:board")
                board_captured = value
            else:
                if current.captured_at is not None and current.captured_at != board_captured:
                    raise NhlLinesIntakeError(f"NHL_INTAKE_CAPTURED_AT_DUPLICATE:{current.header}")
                current.captured_at = value
            continue
        if "@" in line and not line[0].isdigit() and not line.upper().startswith(("ML", "PL", "PUCK", "TOTAL", "TT")):
            away, home = [p.strip() for p in line.split("@", 1)]
            if not away or not home:
                raise NhlLinesIntakeError(f"NHL_INTAKE_HEADER_INVALID:{line}")
            if away.casefold() == home.casefold():
                raise NhlLinesIntakeError(f"NHL_INTAKE_TEAMS_IDENTICAL:{line}")
            current = NhlGameTicket(away=away, home=home, header=line, captured_at=board_captured)
            games.append(current)
            continue
        if current is None:
            raise NhlLinesIntakeError(f"NHL_INTAKE_MARKET_BEFORE_GAME:{line}")
        parts = line.replace(",", " ").split()
        kind = parts[0].lower() if parts else ""
        if kind in {"ml", "moneyline"}:
            if len(parts) != 3:
                raise NhlLinesIntakeError(f"NHL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NhlMarketLine("MONEYLINE", None, _american(parts[1]), _american(parts[2]), line))
        elif kind in {"pl", "puck", "puckline"}:
            if len(parts) != 4:
                raise NhlLinesIntakeError(f"NHL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NhlMarketLine("PUCK_LINE", _line_value(parts[1], line), _american(parts[2]), _american(parts[3]), line))
        elif kind in {"total", "ou"}:
            if len(parts) != 4:
                raise NhlLinesIntakeError(f"NHL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NhlMarketLine("TOTAL", _line_value(parts[1], line), _american(parts[2]), _american(parts[3]), line))
        else:
            raise NhlLinesIntakeError(f"NHL_INTAKE_UNRECOGNIZED:{line}")
    if not games:
        raise NhlLinesIntakeError("NHL_INTAKE_NO_GAMES")
    for game in games:
        if not game.markets:
            raise NhlLinesIntakeError(f"NHL_INTAKE_GAME_WITHOUT_MARKETS:{game.header}")
    return games


def tickets_to_dict(tickets: list[NhlGameTicket], *, observed_at: str) -> dict[str, Any]:
    return {
        "sport": "NHL",
        "observed_at": observed_at,
        "games": [
            {
                "away": g.away,
                "home": g.home,
                "header": g.header,
                "captured_at": g.captured_at,
                "markets": [
                    {
                        "market": m.market,
                        "line": m.line,
                        "away_or_over_price": m.away_or_over_price,
                        "home_or_under_price": m.home_or_under_price,
                        "raw": m.raw,
                    }
                    for m in g.markets
                ],
            }
            for g in tickets
        ],
    }
