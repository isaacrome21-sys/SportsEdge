"""Parse phone CFB lines. Fail closed on one-sided rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class CfbLinesIntakeError(ValueError):
    pass


@dataclass
class CfbMarketLine:
    market: str
    line: float | None
    away_or_over_price: int
    home_or_under_price: int
    raw: str


@dataclass
class CfbGameTicket:
    away: str
    home: str
    header: str
    markets: list[CfbMarketLine] = field(default_factory=list)


def _american(token: str) -> int:
    try:
        value = int(float(token.strip()))
    except ValueError as exc:
        raise CfbLinesIntakeError(f"CFB_INTAKE_ODDS_INVALID:{token}") from exc
    if -100 < value < 100:
        raise CfbLinesIntakeError(f"CFB_INTAKE_ODDS_INVALID:{token}")
    return value


def parse_cfb_lines(body: str) -> list[CfbGameTicket]:
    games: list[CfbGameTicket] = []
    current: CfbGameTicket | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("###"):
            continue
        if "@" in line and not line[0].isdigit() and not line.upper().startswith(("ML", "SPREAD", "TOTAL", "TT")):
            away, home = [p.strip() for p in line.split("@", 1)]
            if not away or not home:
                raise CfbLinesIntakeError(f"CFB_INTAKE_HEADER_INVALID:{line}")
            current = CfbGameTicket(away=away, home=home, header=line)
            games.append(current)
            continue
        if current is None:
            raise CfbLinesIntakeError(f"CFB_INTAKE_MARKET_BEFORE_GAME:{line}")
        parts = line.replace(",", " ").split()
        kind = parts[0].lower() if parts else ""
        if kind in {"ml", "moneyline"}:
            if len(parts) != 3:
                raise CfbLinesIntakeError(f"CFB_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(CfbMarketLine("MONEYLINE", None, _american(parts[1]), _american(parts[2]), line))
        elif kind in {"spread", "rl"}:
            if len(parts) != 4:
                raise CfbLinesIntakeError(f"CFB_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(CfbMarketLine("SPREAD", float(parts[1]), _american(parts[2]), _american(parts[3]), line))
        elif kind in {"total", "ou"}:
            if len(parts) != 4:
                raise CfbLinesIntakeError(f"CFB_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(CfbMarketLine("TOTAL", float(parts[1]), _american(parts[2]), _american(parts[3]), line))
        else:
            raise CfbLinesIntakeError(f"CFB_INTAKE_UNRECOGNIZED:{line}")
    if not games:
        raise CfbLinesIntakeError("CFB_INTAKE_NO_GAMES")
    return games


def tickets_to_dict(tickets: list[CfbGameTicket], *, observed_at: str) -> dict[str, Any]:
    return {
        "sport": "CFB",
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
