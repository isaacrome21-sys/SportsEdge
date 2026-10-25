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


def parse_nfl_lines(body: str) -> list[NflGameTicket]:
    """Parse a compact two-sided board.

    Supported examples::

        Chiefs @ Ravens
        Captured 2026-10-25T11:58:30-05:00
        ML +125 -145
        Spread +3.5 -110 -110
        Total 47.5 -108 -112
        TeamTotal Ravens 24.5 -110 -110
        Prop "Lamar Jackson" PassYards 245.5 -110 -110
        Prop "Derrick Henry" RushYards 82.5 -115 -105

    For spreads the entered line is the AWAY line, matching the legacy phone
    contract. Team-total and player-prop prices are OVER then UNDER.

    ``Captured <ISO-8601 instant with offset>`` (one per game, after the header)
    is when the prices were read off the sportsbook. It becomes every market's
    ``quote_retrieved_at``. Without it the card refuses residual pricing.
    """
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
        capture = CAPTURE_LINE_RE.match(line)
        if capture:
            if current.captured_at is not None:
                raise NflLinesIntakeError(f"NFL_INTAKE_CAPTURED_AT_DUPLICATE:{current.header}")
            current.captured_at = _captured_at(capture.group(1), line)
            continue
        try:
            parts = shlex.split(line.replace(",", " "))
        except ValueError as exc:
            raise NflLinesIntakeError(f"NFL_INTAKE_QUOTING_INVALID:{line}") from exc
        if not parts:
            continue
        kind = parts[0].lower().replace("_", "").replace("-", "")

        if kind in {"ml", "moneyline"}:
            if len(parts) != 3:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(
                NflMarketLine("moneyline", None, _american(parts[1]), _american(parts[2]), line)
            )
            continue

        if kind in {"spread", "rl", "line"}:
            if len(parts) != 4:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(
                NflMarketLine(
                    "spread", _line_value(parts[1], line),
                    _american(parts[2]), _american(parts[3]), line,
                )
            )
            continue

        if kind in {"total", "ou"}:
            if len(parts) != 4:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            current.markets.append(
                NflMarketLine(
                    "total", _line_value(parts[1], line),
                    _american(parts[2]), _american(parts[3]), line,
                )
            )
            continue

        if kind in {"teamtotal", "tt"}:
            if len(parts) < 5:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            team_text = " ".join(parts[1:-3]).strip()
            if not team_text:
                raise NflLinesIntakeError(f"NFL_INTAKE_TEAM_TOTAL_TEAM_MISSING:{line}")
            try:
                team = resolve_team(team_text)
            except NflTeamAliasError as exc:
                raise NflLinesIntakeError(str(exc)) from exc
            if team not in {current.away, current.home}:
                raise NflLinesIntakeError(f"NFL_INTAKE_TEAM_NOT_IN_GAME:{team}")
            current.markets.append(
                NflMarketLine(
                    "team_total", _line_value(parts[-3], line),
                    _american(parts[-2]), _american(parts[-1]), line,
                    team=team,
                )
            )
            continue

        if kind in {"prop", "player"}:
            if len(parts) < 6:
                raise NflLinesIntakeError(f"NFL_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
            player = " ".join(parts[1:-4]).strip()
            if not player:
                raise NflLinesIntakeError(f"NFL_INTAKE_PROP_PLAYER_MISSING:{line}")
            market = _prop_market(parts[-4])
            current.markets.append(
                NflMarketLine(
                    market, _line_value(parts[-3], line),
                    _american(parts[-2]), _american(parts[-1]), line,
                    player=player,
                )
            )
            continue

        raise NflLinesIntakeError(f"NFL_INTAKE_UNRECOGNIZED:{line}")
    if not games:
        raise NflLinesIntakeError("NFL_INTAKE_NO_GAMES")
    for game in games:
        if not game.markets:
            raise NflLinesIntakeError(f"NFL_INTAKE_GAME_WITHOUT_MARKETS:{game.header}")
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
