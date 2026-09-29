"""Turn lines typed on a phone into the canonical manual MLB input file.

Paste a board into a GitHub issue; this module parses it and resolves each game
against the MLB schedule so the card workflow can run with no agent in the loop.
It only transcribes prices. It never creates or changes a probability.

Format (one item per line, blank lines ignored, away/over/yes price first):

    Red Sox @ Yankees
    ML +120 -145
    RL +1.5 -193 +159          (away line/price first; use -1.5 if away is favorite)
    Total 6 -112 -107          (over, under)
    YRFI +135 -170             (yes, no)
    Yankees TT 3.5 +114 -145  (over, under)
    Payton Tolle outs 16.5 +107 -135

Lines carry no sportsbook timestamp, so every row is stamped at issue intake
(or the edit that triggered a rerun) and labeled timestamp_source=INTAKE_STAMPED.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from .mlb_source import GameSnapshot, parse_game_start


class LinesIntakeError(ValueError):
    pass


_PRICE = r"([+-]?\d{3,5}|EVEN|EV)"
_NUM = r"(\d+(?:\.\d+)?)"
_SIGNED_NUM = r"([+-]?\d+(?:\.\d+)?)"
_PLAYER_STATS = {
    "outs": "PITCHER_OUTS", "outs recorded": "PITCHER_OUTS",
    "ks": "PITCHER_STRIKEOUTS", "k": "PITCHER_STRIKEOUTS", "strikeouts": "PITCHER_STRIKEOUTS",
    "hits allowed": "PITCHER_HITS_ALLOWED", "walks allowed": "PITCHER_WALKS",
    "er": "PITCHER_EARNED_RUNS", "earned runs": "PITCHER_EARNED_RUNS",
    "hits": "BATTER_HITS", "tb": "BATTER_TOTAL_BASES", "total bases": "BATTER_TOTAL_BASES",
    "hr": "BATTER_HOME_RUNS", "home runs": "BATTER_HOME_RUNS", "rbi": "BATTER_RBI", "rbis": "BATTER_RBI",
    "runs": "BATTER_RUNS", "hrr": "HITS_RUNS_RBIS", "h+r+rbi": "HITS_RUNS_RBIS",
}


def _price(text: str) -> int:
    t = text.upper()
    if t in {"EVEN", "EV"}:
        return 100
    value = int(t)
    if -100 < value < 100:
        raise LinesIntakeError(f"BAD_PRICE:{text}")
    return value


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


@dataclass(frozen=True)
class ParsedRow:
    away: str
    home: str
    market_type: str
    side: str
    line: float
    price: int
    paired_side: str
    paired_price: int
    subject_name: str | None = None
    team: str | None = None


def parse_lines(text: str) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    game: tuple[str, str] | None = None
    errors: list[str] = []
    for n, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip().strip("`").strip()
        if not line or line.startswith("#") or line.startswith("_"):
            continue
        header = re.fullmatch(r"(.+?)\s*(?:@|\bat\b|\bvs\b\.?)\s*(.+)", line, flags=re.I)
        if header and not re.search(r"[+-]?\d{3}", line):
            game = (header.group(1).strip(), header.group(2).strip())
            continue
        if game is None:
            errors.append(f"line {n}: no game header (e.g. 'Red Sox @ Yankees') before '{line}'")
            continue
        away, home = game
        m = re.fullmatch(rf"(?:ML|moneyline)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if m:
            rows.append(ParsedRow(away, home, "MONEYLINE", "AWAY", 0.0, _price(m[1]), "HOME", _price(m[2])))
            continue
        m = re.fullmatch(rf"(?:RL|run ?line)\s+{_SIGNED_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if m:
            rows.append(ParsedRow(away, home, "RUN_LINE", "AWAY", float(m[1]), _price(m[2]), "HOME", _price(m[3])))
            continue
        m = re.fullmatch(rf"(?:total|o/?u|game total)\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if m:
            rows.append(ParsedRow(away, home, "GAME_TOTAL", "OVER", float(m[1]), _price(m[2]), "UNDER", _price(m[3])))
            continue
        m = re.fullmatch(rf"(YRFI|NRFI)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if m:
            first, second = _price(m[2]), _price(m[3])
            # Canonical engine orientation is YRFI (YES=OVER, NO=UNDER).
            # For an NRFI quote, NRFI YES is therefore canonical YRFI NO.
            yes, no = (first, second) if m[1].upper() == "YRFI" else (second, first)
            rows.append(ParsedRow(away, home, "FIRST_INNING_TOTAL", "OVER", 0.5, yes, "UNDER", no))
            continue
        m = re.fullmatch(rf"(.+?)\s+(?:TT|team total)\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if m:
            rows.append(ParsedRow(away, home, "TEAM_TOTAL", "OVER", float(m[2]), _price(m[3]), "UNDER",
                                  _price(m[4]), team=m[1].strip()))
            continue
        stats = "|".join(sorted((re.escape(k) for k in _PLAYER_STATS), key=len, reverse=True))
        m = re.fullmatch(rf"(.+?)\s+({stats})\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if m:
            rows.append(ParsedRow(away, home, _PLAYER_STATS[m[2].lower()], "OVER", float(m[3]), _price(m[4]),
                                  "UNDER", _price(m[5]), subject_name=m[1].strip()))
            continue
        errors.append(
            f"line {n}: couldn't read '{line}' (need both prices; for run lines include the away line sign, "
            "e.g. 'RL +1.5 -190 +160' or 'RL -1.5 +160 -190')"
        )
    if errors:
        raise LinesIntakeError("\n".join(errors))
    if not rows:
        raise LinesIntakeError("no lines found")
    return rows


def _match_team(name: str, full_names: Iterable[str]) -> list[str]:
    want = _norm(name)
    hits = []
    for full_name in full_names:
        full = _norm(full_name)
        if want and (full == want or full.endswith(" " + want) or full.startswith(want + " ")):
            hits.append(full_name)
    return hits


def resolve_game(away: str, home: str, schedule: list[GameSnapshot]) -> GameSnapshot:
    hits = [g for g in schedule if g.away_name in _match_team(away, [g.away_name])
            and g.home_name in _match_team(home, [g.home_name])]
    if len(hits) != 1:
        raise LinesIntakeError(f"GAME_NOT_FOUND: '{away} @ {home}' matched {len(hits)} games on this slate")
    return hits[0]


def build_input(text: str, *, observed_at: str, schedule: list[GameSnapshot], book: str = "draftkings") -> dict[str, Any]:
    out = []
    for row in parse_lines(text):
        g = resolve_game(row.away, row.home, schedule)
        record: dict[str, Any] = {
            "game_id": f"{g.away_name}@{g.home_name}", "market_type": row.market_type,
            "side": row.side, "line": row.line, "price": row.price,
            "paired_side": row.paired_side, "paired_price": row.paired_price, "book": book,
            "observed_at": observed_at,
            "first_pitch_at": parse_game_start(g.game_date).isoformat(),
            "source": "MANUAL", "timestamp_source": "INTAKE_STAMPED",
        }
        if row.subject_name:
            record["subject_name"] = row.subject_name
        if row.team:
            if _match_team(row.team, [g.home_name]):
                record["team_side"] = "HOME"
            elif _match_team(row.team, [g.away_name]):
                record["team_side"] = "AWAY"
            else:
                raise LinesIntakeError(f"TEAM_NOT_IN_GAME: '{row.team}' in {g.away_name} @ {g.home_name}")
        out.append(record)
    return {"rows": out}
