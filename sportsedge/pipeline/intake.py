"""Shared phone lines-issue parser (every sport).

Issue format (Muse format)::

    Away @ Home                       <- line 1 (issue title is the fallback)
    Captured: 2026-10-25T11:58:30-05:00
    <!-- notes, ignored (may span lines) -->
    ML +125 -145                      <- one market per line, BOTH sides
    Spread +3.5 -110 -110             <- away line, away price, home price
    Total 47.5 -108 -112              <- line, over price, under price
    Ravens TT 24.5 -110 -110          <- subject + market + line + over/under
    Lamar Jackson Pass Yards 245.5 -110 -110

Rules (identical for every sport):
* ``Captured:`` must be an ISO-8601 instant with an explicit offset. Before the
  first market it applies to the whole board; after a header it applies to that
  game. Duplicates in the same scope and malformed values fail closed. A body
  without it parses, but ``captured_at`` is None and a warning is recorded.
* A line with exactly one price fails closed (no side is ever invented). A
  recognised market with the wrong shape fails closed.
* A line whose market label the sport adapter does not know is skipped with a
  warning (``SKIPPED_UNKNOWN``), never guessed.
* Prices are transcribed only. Nothing here creates a probability.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any

from sportsedge.mlb_issue_body import IssueLinesError, extract_issue_lines

from .adapters import MarketSpec, SportAdapter, adapter_for


class SharedIntakeError(ValueError):
    pass


@dataclass(frozen=True)
class SharedMarket:
    market: str             # adapter canonical market name (sport vocabulary)
    family: str             # moneyline | spread | total | team_total | prop | yes_no
    line: float | None
    side_a: str             # AWAY | OVER | YES
    price_a: int
    side_b: str             # HOME | UNDER | NO
    price_b: int
    raw: str
    subject: str | None = None   # player or team text for subject markets
    team: str | None = None      # adapter-resolved team when subject is a team


@dataclass
class SharedGame:
    away: str
    home: str
    header: str
    captured_at: str | None = None
    markets: list[SharedMarket] = field(default_factory=list)


@dataclass
class SharedBoard:
    sport: str
    games: list[SharedGame]
    warnings: list[str]
    board_captured_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_CAPTURED = re.compile(r"^captured\b\s*:?\s*(.*?)\s*$", re.IGNORECASE)
_SPORT_TAG = re.compile(r"^\[[A-Z]{2,4} LINES\]\s*", re.IGNORECASE)
_DROP_WORDS = {"prop", "player", "o/u"}


def _norm_dash(text: str) -> str:
    return text.replace("−", "-").replace("–", "-").replace("—", " — ")


def parse_captured_at(token: str, raw: str, sport: str) -> str:
    """ISO-8601 instant with explicit offset -> normalized isoformat."""
    token = token.strip().strip("`")
    if not token or " " in token or "T" not in token.upper():
        raise SharedIntakeError(f"{sport}_INTAKE_CAPTURED_AT_INVALID:{raw}")
    try:
        value = datetime.fromisoformat(token.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise SharedIntakeError(f"{sport}_INTAKE_CAPTURED_AT_INVALID:{raw}") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise SharedIntakeError(f"{sport}_INTAKE_CAPTURED_AT_TZ_REQUIRED:{raw}")
    return value.isoformat()


def american(token: str, raw: str, sport: str) -> int:
    text = token.strip()
    if text.lower() in {"even", "ev"}:
        return 100
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise SharedIntakeError(f"{sport}_INTAKE_ODDS_INVALID:{raw}") from exc
    if (not number.is_finite() or not isfinite(float(number))
            or number != number.to_integral_value() or -100 < number < 100):
        raise SharedIntakeError(f"{sport}_INTAKE_ODDS_INVALID:{raw}")
    return int(number)


def _number(token: str, raw: str, sport: str) -> float:
    text = token.strip().lstrip("oOuU")
    if text.lower() in {"pk", "pick"}:
        return 0.0
    try:
        value = float(text)
    except ValueError as exc:
        raise SharedIntakeError(f"{sport}_INTAKE_LINE_INVALID:{raw}") from exc
    if not isfinite(value):
        raise SharedIntakeError(f"{sport}_INTAKE_LINE_INVALID:{raw}")
    return value


def parse_header(line: str) -> tuple[str, str] | None:
    """'Away @ Home — context' -> (away, home); None when not a matchup line."""
    text = _SPORT_TAG.sub("", _norm_dash(line.strip()))
    head = re.split(r"\s+—\s+|\s*[(,|]|\s+-\s+|:\s", text, maxsplit=1)[0].strip()
    if "@" not in head or re.search(r"(?<![\w.])[+-]?\d{3,5}(?![\w.])", head):
        return None
    away, home = (part.strip() for part in head.split("@", 1))
    if not away or not home or "@" in home:
        return None
    return away, home


def _numeric(token: str) -> bool:
    text = token.strip().lstrip("oOuU") or token
    if text.lower() in {"even", "ev", "pk", "pick", "nan", "inf", "-inf", "+inf"}:
        return True
    try:
        float(text)
    except ValueError:
        return False
    return True


def _tokens(line: str, sport: str) -> list[str]:
    cleaned = _norm_dash(line).replace(",", " ").replace("/", " ")
    try:
        return shlex.split(cleaned)
    except ValueError as exc:
        raise SharedIntakeError(f"{sport}_INTAKE_QUOTING_INVALID:{line}") from exc


def _match_spec(label_tokens: list[str], adapter: SportAdapter) -> tuple[MarketSpec, str | None] | None:
    """Longest market label at the start (subject after) or end (subject before)."""
    words = [w for w in label_tokens if w.lower() not in _DROP_WORDS]
    n = len(words)
    for size in range(n, 0, -1):
        spec = adapter.market(" ".join(words[:size]))
        if spec is not None:
            rest = " ".join(words[size:]).strip() or None
            return spec, rest
        spec = adapter.market(" ".join(words[n - size:]))
        if spec is not None:
            rest = " ".join(words[:n - size]).strip() or None
            return spec, rest
    return None


def _unknown(line: str, n: int, sport: str, warnings: list[str], strict: bool) -> None:
    if strict:
        raise SharedIntakeError(f"{sport}_INTAKE_UNRECOGNIZED:{line}")
    warnings.append(f"line {n}: SKIPPED_UNKNOWN '{line[:120]}'")


def _parse_market(line: str, game: SharedGame, adapter: SportAdapter, warnings: list[str],
                  n: int, resolve_teams: bool, strict: bool) -> SharedMarket | None:
    sport = adapter.sport
    toks = _tokens(line, sport)
    tail: list[str] = []
    # Many DK/Muse spread and puck-line boards include the *explicit*
    # opposite handicap: `PL -1.5 +164 +1.5 -198`. Keep all four tokens
    # so the paired spread is checked instead of silently skipped.
    while toks and _numeric(toks[-1]) and len(tail) < 6:
        tail.insert(0, toks.pop())
    if not tail:
        warnings.append(f"line {n}: SKIPPED_NOTE '{line[:120]}'")
        return None
    found = _match_spec(toks, adapter) if toks else None
    if found is None:
        if len(tail) == 1:
            raise SharedIntakeError(f"{sport}_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
        return _unknown(line, n, sport, warnings, strict)
    spec, subject = found
    explicit_opposite = spec.family == "spread" and len(tail) == 4
    want = 3 if spec.needs_line else 2
    if len(tail) != want and not explicit_opposite:
        raise SharedIntakeError(f"{sport}_INTAKE_ONE_SIDED_OR_MALFORMED:{line}")
    number = tail[0] if spec.needs_line else None
    if explicit_opposite:
        first_line = _number(tail[0], line, sport)
        second_line = _number(tail[2], line, sport)
        if abs(first_line + second_line) > 1e-9:
            raise SharedIntakeError(f"{sport}_INTAKE_SPREAD_PAIR_MISMATCH:{line}")
        prices = [tail[1], tail[3]]
    else:
        prices = tail[-2:]
    if spec.subject is None and subject:
        return _unknown(line, n, sport, warnings, strict)
    if spec.subject is not None and not subject:
        raise SharedIntakeError(f"{sport}_INTAKE_SUBJECT_MISSING:{line}")
    first = american(prices[0], line, sport)
    second = american(prices[1], line, sport)
    if spec.swap:
        first, second = second, first
    team = None
    if spec.subject == "team" and subject:
        team = adapter.team(subject) if resolve_teams else subject
        if resolve_teams and team not in {game.away, game.home}:
            raise SharedIntakeError(f"{sport}_INTAKE_TEAM_NOT_IN_GAME:{subject}")
    line_value = _number(number, line, sport) if number is not None else spec.fixed_line
    return SharedMarket(spec.market, spec.family, line_value, spec.sides[0], first,
                        spec.sides[1], second, line, subject=subject, team=team)


def issue_lines(body: str, sport: str) -> str:
    """Envelope only: '### Lines' section / fenced blocks, then drop HTML comments."""
    body = _COMMENT.sub("", str(body or ""))
    try:
        return extract_issue_lines(body, sport=sport)
    except IssueLinesError as exc:
        raise SharedIntakeError(str(exc)) from exc


def parse_issue(body: str, sport: str, *, title: str | None = None,
                resolve_teams: bool = True, strict_unknown: bool = False) -> SharedBoard:
    """Parse a lines issue. ``strict_unknown`` (legacy, per entrypoint) turns a
    priced line with an unknown market label into an error instead of a
    warning; the owner default is skip-with-warning."""
    adapter = adapter_for(sport)
    sport = adapter.sport
    text = issue_lines(body, sport)
    warnings: list[str] = []
    games: list[SharedGame] = []
    current: SharedGame | None = None
    board_captured: str | None = None
    own_capture: set[int] = set()

    def _new_game(away: str, home: str, header: str) -> SharedGame:
        if resolve_teams:
            away, home = adapter.team(away), adapter.team(home)
        if away.casefold() == home.casefold():
            raise SharedIntakeError(f"{sport}_INTAKE_TEAMS_IDENTICAL:{header}")
        game = SharedGame(away, home, header, captured_at=board_captured)
        games.append(game)
        return game

    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().strip("`").strip()
        if not line or line.startswith("#"):
            continue
        capture = _CAPTURED.match(line)
        if capture:
            value = parse_captured_at(capture.group(1), line, sport)
            if current is None:
                if board_captured is not None:
                    raise SharedIntakeError(f"{sport}_INTAKE_CAPTURED_AT_DUPLICATE:board")
                board_captured = value
            else:
                if id(current) in own_capture:
                    raise SharedIntakeError(f"{sport}_INTAKE_CAPTURED_AT_DUPLICATE:{current.header}")
                own_capture.add(id(current))
                current.captured_at = value
            continue
        header = parse_header(line)
        if header:
            current = _new_game(header[0], header[1], line)
            continue
        if current is None:
            title_header = parse_header(title or "")
            if not games and title_header:
                current = _new_game(title_header[0], title_header[1], str(title))
            elif not re.search(r"(?<![\w.])[+-]?\d{3,5}(?![\w.])", line):
                warnings.append(f"line {n}: SKIPPED_NOTE '{line[:120]}'")
                continue
            else:
                raise SharedIntakeError(f"{sport}_INTAKE_MARKET_BEFORE_GAME:{line}")
        market = _parse_market(line, current, adapter, warnings, n, resolve_teams, strict_unknown)
        if market is not None:
            current.markets.append(market)

    if not games:
        raise SharedIntakeError(f"{sport}_INTAKE_NO_GAMES")
    for game in games:
        if not game.markets:
            raise SharedIntakeError(f"{sport}_INTAKE_GAME_WITHOUT_MARKETS:{game.header}")
        if game.captured_at is None:
            warnings.append(f"{sport}_INTAKE_NO_CAPTURED_LINE:{game.header}")
    return SharedBoard(sport, games, warnings, board_captured_at=board_captured)


@dataclass
class Envelope:
    """Shared issue envelope for sports whose market grammar is still their own."""
    text: str                       # lines with notes and Captured lines removed
    captured_at: str | None
    header: tuple[str, str] | None  # first 'Away @ Home' (body line 1, else title)
    warnings: list[str]


def parse_envelope(body: str, sport: str, *, title: str | None = None) -> Envelope:
    """Strip ``<!-- -->`` notes, read the board ``Captured:`` line, find the header.

    Offset required. An envelope carries exactly one capture instant, so a
    second ``Captured:`` line anywhere in the body (before or after a header)
    fails closed instead of silently keeping the first value.
    The returned ``text`` keeps every market line for the sport's own grammar.
    """
    sport = adapter_for(sport).sport
    text = issue_lines(body, sport)
    kept: list[str] = []
    captured: str | None = None
    header: tuple[str, str] | None = None
    warnings: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        match = _CAPTURED.match(line)
        if match:
            value = parse_captured_at(match.group(1), line, sport)
            if captured is not None:
                raise SharedIntakeError(f"{sport}_INTAKE_CAPTURED_AT_DUPLICATE:envelope")
            captured = value
            continue
        if header is None and line:
            header = parse_header(line)
        kept.append(raw)
    if header is None and title:
        header = parse_header(title)
    if captured is None:
        warnings.append(f"{sport}_INTAKE_NO_CAPTURED_LINE")
    return Envelope("\n".join(kept).strip(), captured, header, warnings)
