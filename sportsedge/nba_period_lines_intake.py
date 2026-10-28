"""DraftKings NBA period-lines capture grammar — prereg draft §4.2.

The period-lines preregistration draft (PR #2843) §4 gate 2: rows price
and grade only from timestamped DraftKings captures under the standing
lane cadence, and *"the capture grammar must record the four period
sections per game, with ``NOT_OFFERED`` stated explicitly where DK does
not post a section — never a silently shrunk census."* This module is
that grammar extension. It adds no capture scope: period markets are
recorded only for NBA games already in lane coverage, on the same
T-1H / FINAL issue bodies as the full-game lines.

Grammar (one game block, away first, exactly as the lane posts it)::

    Nets @ Celtics
    Captured: 2026-10-27T18:31:00-04:00
    ML +110 -130
    Spread +2.5 -110 -110
    Total 224.5 -110 -110
    Q1 Total 56.5 -110 -110            <- game quarter total (OVER, UNDER)
    Q2 Total 55.5 -108 -112
    Q3 Total NOT_OFFERED               <- section explicitly not posted
    Q4 Total 54.5 -110 -110
    1H Total 111.5 -110 -110           <- game half total
    2H Total 109.5 -110 -110
    Celtics Q1 TT 29.5 -110 -110       <- team period total (OVER, UNDER)
    Nets Q1 TT 27.5 -110 -110
    Celtics Q3 TT NOT_OFFERED

Rules, all fail-closed with named refusals:

* Priced period lines parse through the shared issue parser
  (``sportsedge.pipeline.intake``) via the NBA adapter's period market
  specs — the same transcription discipline as every other market:
  both prices required, plain ASCII decimals only, no coercion of
  scientific notation / underscores / non-ASCII digits, one quote per
  market per game.
* A period section DK does not post is declared with a bare
  ``NOT_OFFERED`` line in the same label form. It is recorded as a
  NOT_OFFERED quote — never dropped, never priced.
* Census (§4.2): for every game, each of the four prereg subfamilies —
  TEAM_QUARTER_TOTAL, GAME_QUARTER_TOTAL, TEAM_HALF_TOTAL,
  GAME_HALF_TOTAL — must be fully accounted: every window (Q1–Q4 /
  1H–2H), for team subfamilies for BOTH teams, is either a priced quote
  or an explicit NOT_OFFERED declaration. Any gap refuses
  ``NBA_PERIOD_CAPTURE_INCOMPLETE``. A section both priced and declared
  NOT_OFFERED refuses ``NBA_PERIOD_SECTION_CONFLICT``.
* Malformed period lines refuse by name (the shared parser's
  ``NBA_INTAKE_*`` refusals, or this module's ``NBA_PERIOD_*`` ones);
  nothing is coerced and no side is ever invented.

This module records captures only. It prices nothing, starts no clock,
and confers no eligibility; the forward build that consumes these
captures is ``sportsedge/nba_period_forward.py`` (NOT FROZEN).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from sportsedge.pipeline.adapters import NBA as NBA_ADAPTER
from sportsedge.pipeline.intake import (
    SharedIntakeError,
    issue_lines,
    parse_header,
    parse_issue,
)
from sportsedge.sports.nba.lines_card import NBALinesError, team_abbr

WINDOWS_QUARTERS = ("Q1", "Q2", "Q3", "Q4")
WINDOWS_HALVES = ("1H", "2H")
WINDOWS = WINDOWS_QUARTERS + WINDOWS_HALVES

# Canonical adapter market -> (prereg subfamily, window).
MARKET_MAP = {
    "Q1_TOTAL": ("GAME_QUARTER_TOTAL", "Q1"),
    "Q2_TOTAL": ("GAME_QUARTER_TOTAL", "Q2"),
    "Q3_TOTAL": ("GAME_QUARTER_TOTAL", "Q3"),
    "Q4_TOTAL": ("GAME_QUARTER_TOTAL", "Q4"),
    "FIRST_HALF_TOTAL": ("GAME_HALF_TOTAL", "1H"),
    "SECOND_HALF_TOTAL": ("GAME_HALF_TOTAL", "2H"),
    "Q1_TEAM_TOTAL": ("TEAM_QUARTER_TOTAL", "Q1"),
    "Q2_TEAM_TOTAL": ("TEAM_QUARTER_TOTAL", "Q2"),
    "Q3_TEAM_TOTAL": ("TEAM_QUARTER_TOTAL", "Q3"),
    "Q4_TEAM_TOTAL": ("TEAM_QUARTER_TOTAL", "Q4"),
    "FIRST_HALF_TEAM_TOTAL": ("TEAM_HALF_TOTAL", "1H"),
    "SECOND_HALF_TEAM_TOTAL": ("TEAM_HALF_TOTAL", "2H"),
}

SUBFAMILIES = ("TEAM_QUARTER_TOTAL", "GAME_QUARTER_TOTAL",
               "TEAM_HALF_TOTAL", "GAME_HALF_TOTAL")

REFUSAL_CAPTURE_INCOMPLETE = "NBA_PERIOD_CAPTURE_INCOMPLETE"
REFUSAL_SECTION_CONFLICT = "NBA_PERIOD_SECTION_CONFLICT"
REFUSAL_NOT_OFFERED_UNRECOGNIZED = "NBA_PERIOD_NOT_OFFERED_UNRECOGNIZED"
REFUSAL_NOT_OFFERED_TEAM_NOT_IN_GAME = "NBA_PERIOD_NOT_OFFERED_TEAM_NOT_IN_GAME"
REFUSAL_NOT_OFFERED_DUPLICATE = "NBA_PERIOD_NOT_OFFERED_DUPLICATE"
REFUSAL_NOT_OFFERED_BEFORE_GAME = "NBA_PERIOD_NOT_OFFERED_BEFORE_GAME"


class NBAPeriodLinesIntakeError(ValueError):
    pass


def _refuse(reason: str, detail: str = ""):
    raise NBAPeriodLinesIntakeError(f"{reason}:{detail}" if detail else reason)


@dataclass
class PeriodQuote:
    market: str                      # adapter canonical name, e.g. Q1_TOTAL
    subfamily: str                   # prereg §2 subfamily
    window: str                      # Q1..Q4 | 1H | 2H
    team: Optional[str]              # resolved tricode for team subfamilies
    status: str                      # PRICED | NOT_OFFERED
    line: Optional[float]
    over_price: Optional[int]
    under_price: Optional[int]
    raw: str

    def to_dict(self) -> dict[str, Any]:
        return {"market": self.market, "subfamily": self.subfamily,
                "window": self.window, "team": self.team,
                "status": self.status, "line": self.line,
                "over_price": self.over_price,
                "under_price": self.under_price, "raw": self.raw}


@dataclass
class PeriodGameCapture:
    away: str
    home: str
    header: str
    captured_at: Optional[str]
    quotes: list = field(default_factory=list)   # list[PeriodQuote]

    def census(self) -> dict:
        """Per-subfamily accounting: PRICED (all windows priced),
        NOT_OFFERED (no window priced), MIXED (both forms present).
        Completeness itself is enforced at parse time."""
        out = {}
        for sub in SUBFAMILIES:
            qs = [q for q in self.quotes if q.subfamily == sub]
            priced = any(q.status == "PRICED" for q in qs)
            offered_down = any(q.status == "NOT_OFFERED" for q in qs)
            out[sub] = ("MIXED" if priced and offered_down
                        else "PRICED" if priced else "NOT_OFFERED")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"away": self.away, "home": self.home, "header": self.header,
                "captured_at": self.captured_at,
                "census": self.census(),
                "quotes": [q.to_dict() for q in self.quotes]}


_NOT_OFFERED = re.compile(r"^(?P<label>.+?)\s+NOT_OFFERED\s*$", re.IGNORECASE)


def _resolve_label(label: str, game_teams: tuple) -> tuple:
    """Resolve a NOT_OFFERED label to (canonical market, team|None).

    Mirrors the shared parser's label matching (longest market label at
    the start, or at the end with the subject before it) against the
    NBA adapter, restricted to the period market specs."""
    words = label.split()
    n = len(words)
    for size in range(n, 0, -1):
        spec = NBA_ADAPTER.market(" ".join(words[:size]))
        if spec is not None and spec.market in MARKET_MAP:
            rest = " ".join(words[size:]).strip()
            if spec.subject is None and not rest:
                return spec.market, None
            _refuse(REFUSAL_NOT_OFFERED_UNRECOGNIZED, label)
        spec = NBA_ADAPTER.market(" ".join(words[n - size:]))
        if spec is not None and spec.market in MARKET_MAP:
            rest = " ".join(words[:n - size]).strip()
            if spec.subject == "team" and rest:
                try:
                    team = team_abbr(rest)
                except NBALinesError:
                    _refuse(REFUSAL_NOT_OFFERED_UNRECOGNIZED, label)
                if team not in game_teams:
                    _refuse(REFUSAL_NOT_OFFERED_TEAM_NOT_IN_GAME,
                            f"{rest} in '{label}'")
                return spec.market, team
            _refuse(REFUSAL_NOT_OFFERED_UNRECOGNIZED, label)
    _refuse(REFUSAL_NOT_OFFERED_UNRECOGNIZED, label)


def _expected_keys(game: PeriodGameCapture) -> dict:
    """(subfamily, window, team) -> canonical market, for every section
    the §4.2 census requires for this game."""
    out = {}
    inv = {(sub, win, team): market for market, (sub, win) in MARKET_MAP.items()
           for team in ((None,) if sub.startswith("GAME") else (game.home, game.away))}
    for sub in SUBFAMILIES:
        windows = WINDOWS_QUARTERS if "QUARTER" in sub else WINDOWS_HALVES
        teams = (None,) if sub.startswith("GAME") else (game.home, game.away)
        for w in windows:
            for t in teams:
                out[(sub, w, t)] = inv[(sub, w, t)]
    return out


def parse_period_capture(body: str, *, title: str | None = None) -> list:
    """Parse one lane lines issue body into period captures, enforcing
    the §4.2 census per game. Returns list[PeriodGameCapture]."""
    text = issue_lines(body, "NBA")

    # Pass 1: lift NOT_OFFERED declarations out (the shared parser
    # would treat a price-less line as a note; here it is census data),
    # validating each against the game it sits in.
    kept: list[str] = []
    declared: dict = {}          # header -> {(market, team): raw line}
    current_header: Optional[str] = None
    current_teams: Optional[tuple] = None
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        header = parse_header(line) if line else None
        if header:
            try:
                current_teams = (team_abbr(header[0]), team_abbr(header[1]))
            except NBALinesError:
                current_teams = None     # shared parser will refuse it below
            current_header = line
            kept.append(raw)
            continue
        match = _NOT_OFFERED.match(line) if line else None
        if match:
            if current_header is None or current_teams is None:
                _refuse(REFUSAL_NOT_OFFERED_BEFORE_GAME, line)
            market, team = _resolve_label(match.group("label"), current_teams)
            slot = declared.setdefault(current_header, {})
            if (market, team) in slot:
                _refuse(REFUSAL_NOT_OFFERED_DUPLICATE, line)
            slot[(market, team)] = line
            continue
        kept.append(raw)

    # Pass 2: priced lines through the shared parser, strict.
    try:
        board = parse_issue("\n".join(kept), "NBA", title=title,
                            strict_unknown=True)
    except SharedIntakeError as exc:
        raise NBAPeriodLinesIntakeError(str(exc)) from exc

    captures: list = []
    for g in board.games:
        capture = PeriodGameCapture(away=g.away, home=g.home, header=g.header,
                                    captured_at=g.captured_at)
        seen: dict = {}
        for m in g.markets:
            if m.market not in MARKET_MAP:
                continue
            subfamily, window = MARKET_MAP[m.market]
            quote = PeriodQuote(
                market=m.market, subfamily=subfamily, window=window,
                team=m.team, status="PRICED", line=m.line,
                over_price=m.price_a, under_price=m.price_b, raw=m.raw)
            key = (subfamily, window, m.team)
            if key in seen:
                _refuse(REFUSAL_SECTION_CONFLICT,
                        f"duplicate priced section {key}: {m.raw}")
            seen[key] = quote
            capture.quotes.append(quote)
        for (market, team), raw_line in declared.get(g.header, {}).items():
            subfamily, window = MARKET_MAP[market]
            key = (subfamily, window, team)
            if key in seen:
                _refuse(REFUSAL_SECTION_CONFLICT,
                        f"section priced and NOT_OFFERED: {raw_line}")
            quote = PeriodQuote(
                market=market, subfamily=subfamily, window=window,
                team=team, status="NOT_OFFERED", line=None,
                over_price=None, under_price=None, raw=raw_line)
            seen[key] = quote
            capture.quotes.append(quote)
        # §4.2 census: every required section accounted, by name.
        for (subfamily, window, team), market in _expected_keys(capture).items():
            if (subfamily, window, team) not in seen:
                _refuse(REFUSAL_CAPTURE_INCOMPLETE,
                        f"{g.away} @ {g.home}: {subfamily} {window} "
                        f"{team or 'GAME'} ({market}) is neither priced "
                        "nor declared NOT_OFFERED")
        capture.quotes.sort(key=lambda q: (SUBFAMILIES.index(q.subfamily),
                                           WINDOWS.index(q.window),
                                           q.team or ""))
        captures.append(capture)
    return captures


def render_period_capture(capture: PeriodGameCapture) -> str:
    """Render a capture back to the canonical issue-body grammar
    (round-trip: ``parse_period_capture(render_period_capture(c))``
    reproduces c's quotes). Full-game lines are not part of a period
    capture and are not rendered."""
    lines = [f"{capture.away} @ {capture.home}"]
    if capture.captured_at:
        lines.append(f"Captured: {capture.captured_at}")
    team_name = {capture.home: capture.home, capture.away: capture.away}
    label = {}
    for market, (sub, window) in MARKET_MAP.items():
        short = {"Q1": "Q1", "Q2": "Q2", "Q3": "Q3", "Q4": "Q4",
                 "1H": "1H", "2H": "2H"}[window]
        label[market] = (f"{short} Total" if sub.startswith("GAME")
                         else f"{short} TT")
    for q in capture.quotes:
        text = label[q.market]
        if q.team:
            text = f"{team_name[q.team]} {text}"
        if q.status == "NOT_OFFERED":
            lines.append(f"{text} NOT_OFFERED")
        else:
            line = q.line
            line_text = str(int(line)) if float(line) == int(line) else str(line)
            lines.append(f"{text} {line_text} {q.over_price:+d} {q.under_price:+d}")
    return "\n".join(lines) + "\n"


def captures_to_dict(captures: list, *, observed_at: str) -> dict[str, Any]:
    return {"sport": "NBA", "market_scope": "PERIOD_TOTALS",
            "observed_at": observed_at,
            "games": [c.to_dict() for c in captures]}
