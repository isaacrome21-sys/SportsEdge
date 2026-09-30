"""Parse phone NHL lines. Fail closed on one-sided rows."""
from __future__ import annotations

from dataclasses import dataclass, field
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


def _american(token: str) -> int:
    try:
        value = int(float(token.strip()))
    except ValueError as exc:
        raise NhlLinesIntakeError(f"NHL_INTAKE_ODDS_INVALID:{token}") from exc
    if -100 < value < 100:
        raise NhlLinesIntakeError(f"NHL_INTAKE_ODDS_INVALID:{token}")
    return value


def parse_nhl_lines(body: str) -> list[NhlGameTicket]:
    games: list[NhlGameTicket] = []
    current: NhlGameTicket | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("###"):
            continue
        if "@" in line and not line[0].isdigit() and not line.upper().startswith(("ML", "PL", "PUCK", "TOTAL", "TT")):
            away, home = [p.strip() for p in line.split("@", 1)]
            if not away or not home:
                raise NhlLinesIntakeError(f"NHL_INTAKE_HEADER_INVALID:{line}")
            current = NhlGameTicket(away=away, home=home, header=line)
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
            current.markets.append(NhlMarketLine("PUCK_LINE", float(parts[1]), _american(parts[2]), _american(parts[3]), line))
        elif kind in {"total", "ou"}:
            if len(parts) != 4:
                raise NhlLinesIntakeError(f"NHL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NhlMarketLine("TOTAL", float(parts[1]), _american(parts[2]), _american(parts[3]), line))
        else:
            raise NhlLinesIntakeError(f"NHL_INTAKE_UNRECOGNIZED:{line}")
    if not games:
        raise NhlLinesIntakeError("NHL_INTAKE_NO_GAMES")
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
