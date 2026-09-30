"""Parse phone NFL lines. Fail closed on one-sided or unreadable rows."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team


class NflLinesIntakeError(ValueError):
    pass


@dataclass
class NflMarketLine:
    market: str
    line: float | None
    away_or_over_price: int
    home_or_under_price: int
    raw: str


@dataclass
class NflGameTicket:
    away: str
    home: str
    header: str
    markets: list[NflMarketLine] = field(default_factory=list)


def _american(token: str) -> int:
    text = token.strip()
    try:
        value = int(float(text))
    except ValueError as exc:
        raise NflLinesIntakeError(f"NFL_INTAKE_ODDS_INVALID:{token}") from exc
    if -100 < value < 100:
        raise NflLinesIntakeError(f"NFL_INTAKE_ODDS_INVALID:{token}")
    return value


def _header(line: str) -> tuple[str, str] | None:
    if "@" not in line:
        return None
    away, home = [part.strip() for part in line.split("@", 1)]
    if not away or not home:
        raise NflLinesIntakeError(f"NFL_INTAKE_HEADER_INVALID:{line}")
    try:
        return resolve_team(away), resolve_team(home)
    except NflTeamAliasError as exc:
        raise NflLinesIntakeError(str(exc)) from exc


def parse_nfl_lines(body: str) -> list[NflGameTicket]:
    games: list[NflGameTicket] = []
    current: NflGameTicket | None = None
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("###"):
            continue
        header = _header(line)
        if header:
            current = NflGameTicket(away=header[0], home=header[1], header=line)
            games.append(current)
            continue
        if current is None:
            raise NflLinesIntakeError(f"NFL_INTAKE_MARKET_BEFORE_GAME:{line}")
        parts = line.replace(",", " ").split()
        if not parts:
            continue
        kind = parts[0].lower()
        if kind in {"ml", "moneyline"}:
            if len(parts) != 3:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NflMarketLine("moneyline", None, _american(parts[1]), _american(parts[2]), line))
            continue
        if kind in {"spread", "rl", "line"}:
            if len(parts) != 4:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NflMarketLine("spread", float(parts[1]), _american(parts[2]), _american(parts[3]), line))
            continue
        if kind in {"total", "ou"}:
            if len(parts) != 4:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(NflMarketLine("total", float(parts[1]), _american(parts[2]), _american(parts[3]), line))
            continue
        raise NflLinesIntakeError(f"NFL_INTAKE_UNRECOGNIZED:{line}")
    if not games:
        raise NflLinesIntakeError("NFL_INTAKE_NO_GAMES")
    return games


def tickets_to_dict(tickets: list[NflGameTicket], *, observed_at: str) -> dict[str, Any]:
    return {
        "sport": "NFL",
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
