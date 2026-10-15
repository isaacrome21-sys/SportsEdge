#!/usr/bin/env python3
"""Board-text intake for O/U player props (t157, Oct 14 2026).

Ports the paired-sides contract of #2283 (f955f317a) onto main as a
self-contained module (no run_it_browser / run_it_automation deps).

Board shape (the ONLY accepted shape for an O/U stat prop):

    GAME: <Away> @ <Home> | <ISO-8601 kickoff with offset>
    PROP: <Player> (<Team>) | <Market> | <Line> | O (<odds>) | U (<odds>)

``PLAYER_PROP:`` is accepted as an alias of ``PROP:``.

Contract:
* A valid line yields exactly two rows, OVER and UNDER, each carrying
  the board's own American price. No complement is ever computed.
* Every PROP line that is not the valid shape is REFUSED BY NAME and
  never dropped:
    - BOARD_LINE_ONE_SIDED      only one price (bare, O-only, U-only)
    - BOARD_LINE_SIDES_MALFORMED two segments but not exactly O then U
                                 with integer American odds (reversed
                                 U|O, O|O, U|U, wrong letters,
                                 non-numeric / zero / |odds|<100)
    - BOARD_LINE_MALFORMED      prop structure unreadable
    - INTAKE_PROP_UNBOUND_NO_GAME_CONTEXT  no preceding GAME: header
* Any other non-blank, non-comment line is BOARD_LINE_UNRECOGNIZED.
``parse_prop_board`` returns (rows, refusals); the CLI writes run_full
``--lines`` JSON only when there are zero refusals (fail closed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ONE_SIDED = "BOARD_LINE_ONE_SIDED"
SIDES_MALFORMED = "BOARD_LINE_SIDES_MALFORMED"
MALFORMED = "BOARD_LINE_MALFORMED"
UNBOUND = "INTAKE_PROP_UNBOUND_NO_GAME_CONTEXT"
UNRECOGNIZED = "BOARD_LINE_UNRECOGNIZED"
GAME_MALFORMED = "BOARD_GAME_HEADER_MALFORMED"

_HEAD_RE = re.compile(r"^(?:PLAYER_PROP|PROP):\s*(.+?)\s*\((.+?)\)\s*\|\s*(.+?)\s*\|\s*(.+)$")
_LINE_RE = re.compile(r"^\d+(?:\.\d+)?$")
_ODDS_RE = re.compile(r"^[+-]?\d+$")
_SEG_RE = re.compile(r"^([A-Za-z]+)\s*\(\s*([^()]*?)\s*\)$")
_GAME_RE = re.compile(r"^GAME:\s*(.+?)\s*@\s*(.+?)\s*\|\s*(\S+)\s*$")


class BoardRefusal(ValueError):
    def __init__(self, code: str, line: str, detail: str = ""):
        self.code, self.line, self.detail = code, line, detail
        super().__init__(f"{code}:{line}" + (f" ({detail})" if detail else ""))


def _odds(text):
    if not _ODDS_RE.match(text or ""):
        return None
    v = int(text)
    return v if abs(v) >= 100 else None


def parse_game_header(line: str) -> dict:
    m = _GAME_RE.match(line)
    if not m:
        raise BoardRefusal(GAME_MALFORMED, line)
    away, home, ko = m.groups()
    try:
        t = datetime.fromisoformat(ko.replace("Z", "+00:00"))
    except ValueError:
        raise BoardRefusal(GAME_MALFORMED, line, "kickoff not ISO-8601")
    if t.tzinfo is None:
        raise BoardRefusal(GAME_MALFORMED, line, "kickoff needs an offset")
    return {"away": away, "home": home,
            "kickoff": t.astimezone(timezone.utc).isoformat()}


def parse_prop_line(line: str, game: dict | None, sport: str, now: datetime,
                    book: str | None = None) -> list:
    """Return [OVER row, UNDER row] or raise BoardRefusal (never None)."""
    m = _HEAD_RE.match(line.strip())
    if not m:
        raise BoardRefusal(MALFORMED, line)
    player, team, market, rest = (g.strip() for g in m.groups())
    parts = [p.strip() for p in rest.split("|")]
    line_text, segs = parts[0], parts[1:]
    if not _LINE_RE.match(line_text):
        raise BoardRefusal(MALFORMED, line, "line value")
    if len(segs) <= 1:
        raise BoardRefusal(ONE_SIDED, line)
    if len(segs) != 2:
        raise BoardRefusal(SIDES_MALFORMED, line, f"{len(segs)} price segments")
    parsed = []
    for seg in segs:
        sm = _SEG_RE.match(seg)
        if not sm:
            raise BoardRefusal(SIDES_MALFORMED, line, f"segment {seg!r}")
        letter, odds_text = sm.group(1).upper(), sm.group(2)
        odds = _odds(odds_text)
        if odds is None:
            raise BoardRefusal(SIDES_MALFORMED, line, f"odds {odds_text!r}")
        parsed.append((letter, odds))
    if [p[0] for p in parsed] != ["O", "U"]:
        raise BoardRefusal(SIDES_MALFORMED, line,
                           "sides must be exactly O then U, got "
                           + "|".join(p[0] for p in parsed))
    if not game or not game.get("away") or not game.get("home"):
        raise BoardRefusal(UNBOUND, line)
    base = {"sport": sport, "away": game["away"], "home": game["home"],
            "kickoff": game.get("kickoff", ""), "player_name": player,
            "team": team, "market": market.upper().replace(" ", "_"),
            "line": float(line_text),
            "quote_captured_at": now.astimezone(timezone.utc).isoformat()}
    if book:
        base["book"] = book
    return [dict(base, side="OVER", odds=parsed[0][1]),
            dict(base, side="UNDER", odds=parsed[1][1])]


def parse_prop_board(text: str, *, sport: str, now: datetime,
                     book: str | None = None):
    """(rows, refusals). Every PROP line yields 2 rows or 1 refusal."""
    if not sport:
        raise ValueError("SPORT_REQUIRED")
    rows, refusals, game = [], [], None
    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        try:
            if s.startswith("GAME:"):
                game = parse_game_header(s)
            elif s.startswith(("PROP:", "PLAYER_PROP:")):
                rows.extend(parse_prop_line(s, game, sport, now, book))
            else:
                raise BoardRefusal(UNRECOGNIZED, s)
        except BoardRefusal as e:
            refusals.append({"line_no": n, "code": e.code, "line": s,
                             "detail": e.detail})
    return rows, refusals


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--board", required=True, type=Path)
    p.add_argument("--sport", required=True)
    p.add_argument("--captured-at", required=True,
                   help="ISO-8601 capture instant (with offset) of the board")
    p.add_argument("--book")
    p.add_argument("--output", required=True, type=Path)
    a = p.parse_args(argv)
    now = datetime.fromisoformat(a.captured_at.replace("Z", "+00:00"))
    if now.tzinfo is None:
        p.error("--captured-at needs an offset")
    rows, refusals = parse_prop_board(a.board.read_text(encoding="utf-8"),
                                      sport=a.sport.upper(), now=now, book=a.book)
    if refusals:
        json.dump({"refusals": refusals}, sys.stderr, indent=2)
        return 2
    a.output.write_text(json.dumps({"lines": rows}, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
