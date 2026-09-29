"""Turn MLB lines typed on a phone into the canonical manual-input contract.

This is transcription only. It resolves games against the MLB schedule and maps
human-friendly line labels to existing SportsEdge manual market types. It never
creates or changes a probability.

Every row requires both offered prices. The issue open/edit timestamp is retained
as ``INTAKE_STAMPED`` provenance and is explicitly not a sportsbook timestamp.
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

# Ambiguous bare K/strikeouts is intentionally pitcher-oriented, matching the
# common sportsbook shorthand. Batter strikeouts require an explicit batter tag.
_PLAYER_STATS = {
    "outs": "PITCHER_OUTS",
    "outs recorded": "PITCHER_OUTS",
    "k": "PITCHER_STRIKEOUTS",
    "ks": "PITCHER_STRIKEOUTS",
    "strikeouts": "PITCHER_STRIKEOUTS",
    "pitcher k": "PITCHER_STRIKEOUTS",
    "pitcher ks": "PITCHER_STRIKEOUTS",
    "hits allowed": "PITCHER_HITS_ALLOWED",
    "pitcher hits": "PITCHER_HITS_ALLOWED",
    "walks allowed": "PITCHER_WALKS",
    "pitcher walks": "PITCHER_WALKS",
    "er": "PITCHER_EARNED_RUNS",
    "earned runs": "PITCHER_EARNED_RUNS",
    "hits walks er": "PITCHER_HITS_WALKS_ER",
    "hits+walks+er": "PITCHER_HITS_WALKS_ER",
    "h+bb+er": "PITCHER_HITS_WALKS_ER",
    "hits": "BATTER_HITS",
    "tb": "BATTER_TOTAL_BASES",
    "total bases": "BATTER_TOTAL_BASES",
    "hr": "BATTER_HOME_RUNS",
    "home run": "BATTER_HOME_RUNS",
    "home runs": "BATTER_HOME_RUNS",
    "rbi": "BATTER_RBI",
    "rbis": "BATTER_RBI",
    "runs": "BATTER_RUNS",
    "sb": "BATTER_STOLEN_BASES",
    "stolen bases": "BATTER_STOLEN_BASES",
    "bb": "BATTER_WALKS",
    "walks": "BATTER_WALKS",
    "xbh": "EXTRA_BASE_HITS",
    "extra base hits": "EXTRA_BASE_HITS",
    "singles": "SINGLES",
    "doubles": "DOUBLES",
    "triples": "TRIPLES",
    "batter k": "BATTER_STRIKEOUTS",
    "batter ks": "BATTER_STRIKEOUTS",
    "batter strikeouts": "BATTER_STRIKEOUTS",
    "hrr": "HITS_RUNS_RBIS",
    "h+r+rbi": "HITS_RUNS_RBIS",
    "hits+runs+rbi": "HITS_RUNS_RBIS",
    "h+r+sb": "HITS_RUNS_STOLEN_BASES",
    "hits+runs+sb": "HITS_RUNS_STOLEN_BASES",
    "r+rbi": "RUNS_RBIS",
    "runs+rbi": "RUNS_RBIS",
    "h+sb": "HITS_STOLEN_BASES",
    "hits+sb": "HITS_STOLEN_BASES",
    "h+bb+sb": "HITS_WALKS_STOLEN_BASES",
    "hits+walks+sb": "HITS_WALKS_STOLEN_BASES",
}

_EITHER_PITCHER_STATS = {
    "hits allowed": "EITHER_PITCHER_HITS_ALLOWED",
    "walks": "EITHER_PITCHER_WALKS",
    "walks allowed": "EITHER_PITCHER_WALKS",
    "er": "EITHER_PITCHER_EARNED_RUNS",
    "earned runs": "EITHER_PITCHER_EARNED_RUNS",
}


def _price(text: str) -> int:
    value_text = text.upper()
    if value_text in {"EVEN", "EV"}:
        return 100
    value = int(value_text)
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


def _aliases_pattern(values: Iterable[str]) -> str:
    return "|".join(sorted((re.escape(value) for value in values), key=len, reverse=True))


def parse_lines(text: str) -> list[ParsedRow]:
    rows: list[ParsedRow] = []
    game: tuple[str, str] | None = None
    errors: list[str] = []
    player_stats = _aliases_pattern(_PLAYER_STATS)
    either_stats = _aliases_pattern(_EITHER_PITCHER_STATS)

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

        match = re.fullmatch(rf"(?:ML|moneyline)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "MONEYLINE", "AWAY", 0.0, _price(match[1]), "HOME", _price(match[2])))
            continue

        match = re.fullmatch(rf"(?:RL|run ?line)\s+{_SIGNED_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "RUN_LINE", "AWAY", float(match[1]), _price(match[2]), "HOME", _price(match[3])))
            continue

        match = re.fullmatch(rf"(?:total|o/?u|game total)\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "GAME_TOTAL", "OVER", float(match[1]), _price(match[2]), "UNDER", _price(match[3])))
            continue

        match = re.fullmatch(rf"(YRFI|NRFI)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            first, second = _price(match[2]), _price(match[3])
            # Canonical orientation is YRFI: YES=OVER / NO=UNDER. For an NRFI
            # quote, NRFI YES is therefore the canonical YRFI NO price.
            yes, no = (first, second) if match[1].upper() == "YRFI" else (second, first)
            rows.append(ParsedRow(away, home, "FIRST_INNING_TOTAL", "OVER", 0.5, yes, "UNDER", no))
            continue

        match = re.fullmatch(rf"(?:F5|first ?5|first five)\s+(?:ML|moneyline)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "FIRST_FIVE_MONEYLINE", "AWAY", 0.0, _price(match[1]), "HOME", _price(match[2])))
            continue

        match = re.fullmatch(rf"(?:F5|first ?5|first five)\s+(?:RL|run ?line)\s+{_SIGNED_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "FIRST_FIVE_RUN_LINE", "AWAY", float(match[1]), _price(match[2]), "HOME", _price(match[3])))
            continue

        match = re.fullmatch(rf"(?:F5|first ?5|first five)\s+(?:total|o/?u)\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "FIRST_FIVE_TOTAL", "OVER", float(match[1]), _price(match[2]), "UNDER", _price(match[3])))
            continue

        match = re.fullmatch(rf"(.+?)\s+(?:F5|first ?5|first five)\s+(?:TT|team total)\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "FIRST_FIVE_TEAM_TOTAL", "OVER", float(match[2]), _price(match[3]), "UNDER", _price(match[4]), team=match[1].strip()))
            continue

        match = re.fullmatch(rf"(.+?)\s+(?:TT|team total)\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "TEAM_TOTAL", "OVER", float(match[2]), _price(match[3]), "UNDER", _price(match[4]), team=match[1].strip()))
            continue

        match = re.fullmatch(rf"(.+?)\s+(?:pitcher\s+)?(?:win|record win)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "PITCHER_RECORD_WIN", "YES", 0.0, _price(match[2]), "NO", _price(match[3]), subject_name=match[1].strip()))
            continue

        match = re.fullmatch(rf"(.+?)\s+first\s+(?:hr|home run)\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, "FIRST_HOME_RUN", "YES", 0.0, _price(match[2]), "NO", _price(match[3]), subject_name=match[1].strip()))
            continue

        match = re.fullmatch(rf"either\s+pitcher\s+({either_stats})\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            rows.append(ParsedRow(away, home, _EITHER_PITCHER_STATS[match[1].lower()], "OVER", float(match[2]), _price(match[3]), "UNDER", _price(match[4])))
            continue

        match = re.fullmatch(rf"(.+?)\s+({player_stats})\s+{_NUM}\s+{_PRICE}\s+{_PRICE}", line, flags=re.I)
        if match:
            alias = match[2].lower()
            rows.append(ParsedRow(away, home, _PLAYER_STATS[alias], "OVER", float(match[3]), _price(match[4]), "UNDER", _price(match[5]), subject_name=match[1].strip()))
            continue

        errors.append(
            f"line {n}: couldn't read '{line}' (use a supported market and both prices; "
            "for run lines include the away line sign, e.g. 'RL +1.5 -190 +160' or 'RL -1.5 +160 -190')"
        )

    if errors:
        raise LinesIntakeError("\n".join(errors))
    if not rows:
        raise LinesIntakeError("no lines found")
    return rows


def _match_team(name: str, full_names: Iterable[str]) -> list[str]:
    want = _norm(name)
    hits: list[str] = []
    for full_name in full_names:
        full = _norm(full_name)
        if want and (full == want or full.endswith(" " + want) or full.startswith(want + " ")):
            hits.append(full_name)
    return hits


def resolve_game(away: str, home: str, schedule: list[GameSnapshot]) -> GameSnapshot:
    hits = [
        game for game in schedule
        if game.away_name in _match_team(away, [game.away_name])
        and game.home_name in _match_team(home, [game.home_name])
    ]
    if len(hits) != 1:
        raise LinesIntakeError(f"GAME_NOT_FOUND: '{away} @ {home}' matched {len(hits)} games on this slate")
    return hits[0]


def build_input(
    text: str,
    *,
    observed_at: str,
    schedule: list[GameSnapshot],
    book: str = "draftkings",
) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    for row in parse_lines(text):
        game = resolve_game(row.away, row.home, schedule)
        record: dict[str, Any] = {
            "game_id": f"{game.away_name}@{game.home_name}",
            "market_type": row.market_type,
            "side": row.side,
            "line": row.line,
            "price": row.price,
            "paired_side": row.paired_side,
            "paired_price": row.paired_price,
            "book": book,
            "observed_at": observed_at,
            "first_pitch_at": parse_game_start(game.game_date).isoformat(),
            "source": "MANUAL",
            "timestamp_source": "INTAKE_STAMPED",
        }
        if row.subject_name:
            record["subject_name"] = row.subject_name
        if row.team:
            if _match_team(row.team, [game.home_name]):
                record["team_side"] = "HOME"
            elif _match_team(row.team, [game.away_name]):
                record["team_side"] = "AWAY"
            else:
                raise LinesIntakeError(
                    f"TEAM_NOT_IN_GAME: '{row.team}' in {game.away_name} @ {game.home_name}"
                )
        out.append(record)
    return {"rows": out}
