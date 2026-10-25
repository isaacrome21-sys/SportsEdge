"""Parse phone NFL lines for the unified game + player market board.

Every market remains two-sided at intake.  The parser records the exact offered
prices but never turns those prices into model inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
import re
import shlex
from typing import Any

from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team
from sportsedge.pipeline.intake import SharedIntakeError, parse_issue


class NflLinesIntakeError(ValueError):
    pass


PROP_ALIASES = {
    "passattempts": "pass_attempts",
    "passingattempts": "pass_attempts",
    "completions": "completions",
    "passyards": "passing_yards",
    "passingyards": "passing_yards",
    "passtds": "pass_tds",
    "passingtouchdowns": "pass_tds",
    "interceptions": "interceptions",
    "ints": "interceptions",
    "rushattempts": "rush_attempts",
    "rushingattempts": "rush_attempts",
    "carries": "rush_attempts",
    "rushyards": "rushing_yards",
    "rushingyards": "rushing_yards",
    "receptions": "receptions",
    "catches": "receptions",
    "receivingyards": "receiving_yards",
    "recyards": "receiving_yards",
    "rushreceivingyards": "rush_receiving_yards",
    "rushrec": "rush_receiving_yards",
    "receivingtds": "receiving_tds",
    "rushingtds": "rushing_tds",
    "anytimetds": "anytime_tds",
    "anytimetd": "anytime_tds",
    "attd": "anytime_tds",
}


@dataclass
class NflMarketLine:
    market: str
    line: float | None
    away_or_over_price: int
    home_or_under_price: int
    raw: str
    team: str | None = None
    player: str | None = None


@dataclass
class NflGameTicket:
    away: str
    home: str
    header: str
    markets: list[NflMarketLine] = field(default_factory=list)
    # Sportsbook capture instant from the game's own ``Captured`` line. Never
    # derived from the GitHub issue's created/edited time.
    captured_at: str | None = None


CAPTURE_LINE_RE = re.compile(r"^captured\b\s*:?\s*(.*?)\s*$", re.I)


def _captured_at(token: str, raw: str) -> str:
    if not token or " " in token:
        raise NflLinesIntakeError(f"NFL_INTAKE_CAPTURED_AT_INVALID:{raw}")
    try:
        value = datetime.fromisoformat(token.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise NflLinesIntakeError(f"NFL_INTAKE_CAPTURED_AT_INVALID:{raw}") from exc
    if "T" not in token.upper() or value.tzinfo is None or value.utcoffset() is None:
        raise NflLinesIntakeError(f"NFL_INTAKE_CAPTURED_AT_TZ_REQUIRED:{raw}")
    return value.isoformat()


def _american(token: str) -> int:
    text = token.strip()
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise NflLinesIntakeError(f"NFL_INTAKE_ODDS_INVALID:{token}") from exc
    if (not number.is_finite() or not isfinite(float(number))
            or number != number.to_integral_value()
            or -100 < number < 100):
        raise NflLinesIntakeError(f"NFL_INTAKE_ODDS_INVALID:{token}")
    return int(number)


def _line_value(token: str, raw: str) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise NflLinesIntakeError(f"NFL_INTAKE_LINE_INVALID:{raw}") from exc
    if not isfinite(value):
        raise NflLinesIntakeError(f"NFL_INTAKE_LINE_INVALID:{raw}")
    return value


def _header(line: str) -> tuple[str, str] | None:
    if "@" not in line:
        return None
    away, home = [part.strip() for part in line.split("@", 1)]
    if not away or not home:
        raise NflLinesIntakeError(f"NFL_INTAKE_HEADER_INVALID:{line}")
    try:
        away_team, home_team = resolve_team(away), resolve_team(home)
    except NflTeamAliasError as exc:
        raise NflLinesIntakeError(str(exc)) from exc
    if away_team == home_team:
        raise NflLinesIntakeError(f"NFL_INTAKE_TEAMS_IDENTICAL:{line}")
    return away_team, home_team


def _prop_market(token: str) -> str:
    key = "".join(ch for ch in str(token).lower() if ch.isalnum())
    market = PROP_ALIASES.get(key)
    if market is None:
        raise NflLinesIntakeError(f"NFL_INTAKE_PROP_MARKET_UNRECOGNIZED:{token}")
    return market


def parse_nfl_lines(body: str, *, title: str | None = None) -> list[NflGameTicket]:
    """Parse a compact two-sided board via the shared parser.

    Supported examples::

        Chiefs @ Ravens
        Captured 2026-10-25T11:58:30-05:00
        ML +125 -145
        Spread +3.5 -110 -110
        Total 47.5 -108 -112
        TeamTotal Ravens 24.5 -110 -110
        Prop "Lamar Jackson" PassYards 245.5 -110 -110

    For spreads the entered line is the AWAY line. Team-total and player-prop
    prices are OVER then UNDER. ``Captured`` (ISO instant with offset) is when
    the prices were read off DraftKings and becomes ``quote_retrieved_at``.
    Grammar and Captured rules live in ``sportsedge.pipeline.intake``; this
    adapter keeps the NFL ticket shape and error class.
    """
    try:
        board = parse_issue(body, "NFL", title=title, strict_unknown=True)
    except SharedIntakeError as exc:
        raise NflLinesIntakeError(str(exc)) from exc
    games: list[NflGameTicket] = []
    for g in board.games:
        ticket = NflGameTicket(away=g.away, home=g.home, header=g.header, captured_at=g.captured_at)
        for m in g.markets:
            ticket.markets.append(NflMarketLine(
                m.market, m.line, m.price_a, m.price_b, m.raw,
                team=m.team, player=m.subject if m.family == "prop" else None,
            ))
        games.append(ticket)
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
                "captured_at": g.captured_at,
                "markets": [
                    {
                        "market": m.market,
                        "line": m.line,
                        "away_or_over_price": m.away_or_over_price,
                        "home_or_under_price": m.home_or_under_price,
                        "raw": m.raw,
                        "team": m.team,
                        "player": m.player,
                        **({"quote_retrieved_at": g.captured_at} if g.captured_at else {}),
                    }
                    for m in g.markets
                ],
            }
            for g in tickets
        ],
    }
