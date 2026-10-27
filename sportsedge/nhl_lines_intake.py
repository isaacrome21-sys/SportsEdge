"""Parse phone NHL lines. Fail closed on one-sided rows."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from sportsedge.pipeline.intake import SharedIntakeError, parse_issue


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


def parse_nhl_lines(body: str, *, title: str | None = None) -> list[NhlGameTicket]:
    """Thin adapter over the shared parser (``sportsedge.pipeline.intake``)."""
    try:
        board = parse_issue(body, "NHL", title=title, strict_unknown=True)
    except SharedIntakeError as exc:
        raise NhlLinesIntakeError(str(exc)) from exc
    return [
        NhlGameTicket(
            away=g.away, home=g.home, header=g.header, captured_at=g.captured_at,
            markets=[NhlMarketLine(m.market, m.line, m.price_a, m.price_b, m.raw) for m in g.markets],
        )
        for g in board.games
    ]


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
