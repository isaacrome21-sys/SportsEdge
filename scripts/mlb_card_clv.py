#!/usr/bin/env python3
"""Closing-line value for graded SportsEdge MLB card picks (DraftKings only).

Entry quote: the pick's own [MLB LINES] issue body (the pregame quote the card
priced). The posted card price must equal that quote's price for the selected
side, or the pick is NO_ENTRY_QUOTE (never guessed).

Close quote: the last *other* [MLB LINES] issue for the same game whose
``Captured: <ISO>`` line is strictly before first pitch and after the entry
capture, carrying the same market, line and team/subject with both sides
priced. Issues without a Captured line are never used as a close.

CLV = selected-side close fair probability minus entry fair probability, both
two-way multiplicative devig of the DK pair (same method at entry and close).
Positive means the market moved toward the pick. Settlement-only evidence:
this module never changes model probabilities, card status or promotion.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from sportsedge.mlb_issue_body import IssueLinesError, extract_issue_lines
from sportsedge.mlb_lines_intake import (
    LinesIntakeError,
    ParsedRow,
    _match_team,
    parse_lines_with_warnings,
)

CLV_LEDGER = Path("ledger/mlb_clv_ledger.csv")
CLV_FIELDS = [
    "issue_number", "game_pk", "pick", "status", "price", "market_type", "line",
    "entry_captured_at", "entry_fair_p", "close_issue", "close_captured_at",
    "close_price", "close_fair_p", "clv_prob", "clv_status",
]
_CAPTURED = re.compile(r"^\s*captured\s*:?\s*(\S+)\s*$", re.I)

# Grader prop label (lower) -> intake market_type.
_PROP_MARKETS = {
    "pitcher k": "PITCHER_STRIKEOUTS",
    "pitcher outs": "PITCHER_OUTS",
    "pitcher hits allowed": "PITCHER_HITS_ALLOWED",
    "pitcher bb": "PITCHER_WALKS",
    "pitcher er": "PITCHER_EARNED_RUNS",
    "pitcher hits walks er": "PITCHER_HITS_WALKS_ER",
    "hits": "BATTER_HITS",
    "total bases": "BATTER_TOTAL_BASES",
    "home runs": "BATTER_HOME_RUNS",
    "rbi": "BATTER_RBI",
    "runs": "BATTER_RUNS",
    "stolen bases": "BATTER_STOLEN_BASES",
    "batter bb": "BATTER_WALKS",
    "batter k": "BATTER_STRIKEOUTS",
    "extra base hits": "EXTRA_BASE_HITS",
    "singles": "SINGLES",
    "doubles": "DOUBLES",
    "triples": "TRIPLES",
    "hits runs rbis": "HITS_RUNS_RBIS",
    "hits runs stolen bases": "HITS_RUNS_STOLEN_BASES",
    "runs rbis": "RUNS_RBIS",
    "hits stolen bases": "HITS_STOLEN_BASES",
    "hits walks stolen bases": "HITS_WALKS_STOLEN_BASES",
}


@dataclass(frozen=True)
class PickKey:
    market_type: str
    side: str  # side of the selected outcome in intake orientation
    line: float | None  # intake-orientation line (away line for run lines)
    team_side: str | None = None  # AWAY/HOME for team totals
    subject: str | None = None


def parse_captured_at(body: str) -> datetime | None:
    for raw in str(body or "").splitlines()[:6]:
        match = _CAPTURED.match(raw.strip().strip("`"))
        if match:
            try:
                value = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
            except ValueError:
                return None
            return value if value.tzinfo else None
    return None


def _norm(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", folded).split())


def pick_key(pick: str, names: dict[str, str]) -> PickKey | None:
    low = " ".join(pick.lower().split())
    f5 = low.startswith("f5 ") or " f5 " in low
    pre = "FIRST_FIVE_" if f5 else ""
    m = re.fullmatch(r"(?:f5 )?moneyline (away|home)", low)
    if m:
        return PickKey(pre + "MONEYLINE", m.group(1).upper(), 0.0)
    m = re.fullmatch(r"(?:f5 )?run line (away|home) ([+-]?\d+(?:\.\d+)?)", low)
    if m:
        side, line = m.group(1).upper(), float(m.group(2))
        return PickKey(pre + "RUN_LINE", side, line if side == "AWAY" else -line)
    m = re.fullmatch(r"(?:f5 )?totals (over|under) (\d+(?:\.\d+)?)", low)
    if m:
        return PickKey(pre + "TOTAL" if f5 else "GAME_TOTAL", m.group(1).upper(), float(m.group(2)))
    if low in {"yrfi yes", "yrfi", "nrfi no"}:
        return PickKey("FIRST_INNING_TOTAL", "OVER", 0.5)
    if low in {"yrfi no", "nrfi yes", "nrfi"}:
        return PickKey("FIRST_INNING_TOTAL", "UNDER", 0.5)
    for side in ("away", "home"):
        m = re.fullmatch(
            rf"{re.escape(names[side].lower())} (f5 )?team totals (over|under) (\d+(?:\.\d+)?)", low
        )
        if m:
            market = "FIRST_FIVE_TEAM_TOTAL" if m.group(1) else "TEAM_TOTAL"
            return PickKey(market, m.group(2).upper(), float(m.group(3)), team_side=side.upper())
    for label in sorted(_PROP_MARKETS, key=len, reverse=True):
        m = re.fullmatch(rf"(.+?) {re.escape(label)} (over|under) (\d+(?:\.\d+)?)", low)
        if m:
            return PickKey(_PROP_MARKETS[label], m.group(2).upper(), float(m.group(3)), subject=m.group(1))
    m = re.fullmatch(r"(.+?) pitcher record win (yes|no)(?: 0(?:\.0+)?)?", low)
    if m:
        return PickKey("PITCHER_RECORD_WIN", m.group(2).upper(), 0.0, subject=m.group(1))
    return None


def _row_team_side(row: ParsedRow, names: dict[str, str]) -> str | None:
    if not row.team:
        return None
    if _match_team(row.team, [names["away"]]):
        return "AWAY"
    if _match_team(row.team, [names["home"]]):
        return "HOME"
    return None


def _same_game(row: ParsedRow, names: dict[str, str]) -> bool:
    return bool(_match_team(row.away, [names["away"]])) and bool(_match_team(row.home, [names["home"]]))


def find_quote(rows: Iterable[ParsedRow], key: PickKey, names: dict[str, str]) -> tuple[int, int] | None:
    """(selected price, opposite price) for the pick, or None. Ambiguity -> None."""
    hits: list[tuple[int, int]] = []
    for row in rows:
        if row.market_type != key.market_type or not _same_game(row, names):
            continue
        if key.line is not None and float(row.line) != float(key.line):
            continue
        if key.team_side is not None and _row_team_side(row, names) != key.team_side:
            continue
        if key.subject is not None:
            if not row.subject_name:
                continue
            a, b = _norm(row.subject_name), _norm(key.subject)
            if a != b and a.split()[-1:] != b.split()[-1:]:
                continue
        if key.side == row.side:
            hits.append((row.price, row.paired_price))
        elif key.side == row.paired_side:
            hits.append((row.paired_price, row.price))
    unique = set(hits)
    return hits[0] if len(unique) == 1 else None


def _implied(price: int) -> float:
    return 100.0 / (price + 100.0) if price > 0 else abs(price) / (abs(price) + 100.0)


def fair_probability(selected: int, opposite: int) -> float:
    q1, q2 = _implied(selected), _implied(opposite)
    return q1 / (q1 + q2)


def issue_quotes(body: str, title: str | None) -> list[ParsedRow]:
    try:
        text = extract_issue_lines(body)
        return parse_lines_with_warnings(text, title=title)[0]
    except (IssueLinesError, LinesIntakeError, TypeError):
        return []


def compute_clv(
    *,
    issue_number: int,
    picks: Iterable[Any],  # CardRow-like: game_pk, pick, price, status
    feed: dict[str, Any],
    entry_issue: dict[str, Any],
    other_issues: Iterable[dict[str, Any]],
) -> list[dict[str, str]]:
    teams = feed["gameData"]["teams"]
    names = {"away": teams["away"]["name"], "home": teams["home"]["name"]}
    start_text = str(feed.get("gameData", {}).get("datetime", {}).get("dateTime") or "")
    first_pitch = datetime.fromisoformat(start_text.replace("Z", "+00:00")) if start_text else None
    entry_body = str(entry_issue.get("body") or "")
    entry_rows = issue_quotes(entry_body, entry_issue.get("title"))
    entry_at = parse_captured_at(entry_body)

    now = datetime.now(timezone.utc)
    closes: list[tuple[datetime, int, list[ParsedRow]]] = []
    for other in other_issues:
        number = int(other.get("number") or 0)
        if number == issue_number:
            continue
        body = str(other.get("body") or "")
        captured = parse_captured_at(body)
        if captured is None or first_pitch is None or captured >= first_pitch or captured > now:
            continue
        if entry_at is not None and captured <= entry_at:
            continue
        rows = [r for r in issue_quotes(body, other.get("title")) if _same_game(r, names)]
        if rows:
            closes.append((captured, number, rows))
    closes.sort(key=lambda item: (item[0], item[1]), reverse=True)

    out: list[dict[str, str]] = []
    for pick in picks:
        record = {field: "" for field in CLV_FIELDS}
        record.update(
            issue_number=str(issue_number), game_pk=str(pick.game_pk), pick=pick.pick,
            status=pick.status, price=f"{pick.price:+d}",
            entry_captured_at=entry_at.isoformat() if entry_at else "",
        )
        if entry_at is None or first_pitch is None or entry_at > now or entry_at >= first_pitch:
            record["clv_status"] = "NO_ENTRY_CAPTURE"
            out.append(record)
            continue
        key = pick_key(pick.pick, names)
        if key is None:
            record["clv_status"] = "UNMAPPED_MARKET"
            out.append(record)
            continue
        record.update(market_type=key.market_type, line="" if key.line is None else f"{key.line:g}")
        entry = find_quote(entry_rows, key, names)
        if entry is None or entry[0] != pick.price:
            record["clv_status"] = "NO_ENTRY_QUOTE"
            out.append(record)
            continue
        entry_p = fair_probability(*entry)
        record["entry_fair_p"] = f"{entry_p:.6f}"
        close = None
        for captured, number, rows in closes:
            quote = find_quote(rows, key, names)
            if quote is not None:
                close = (captured, number, quote)
                break
        if close is None:
            record["clv_status"] = "NO_CLOSE_QUOTE"
            out.append(record)
            continue
        captured, number, quote = close
        close_p = fair_probability(*quote)
        record.update(
            close_issue=str(number), close_captured_at=captured.isoformat(),
            close_price=f"{quote[0]:+d}", close_fair_p=f"{close_p:.6f}",
            clv_prob=f"{close_p - entry_p:+.6f}", clv_status="CLV_TRACKED",
        )
        out.append(record)
    return out


def upsert_clv_ledger(path: Path, issue_number: int, game_pk: int, records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keep: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            keep = [
                row for row in csv.DictReader(handle)
                if not (row.get("issue_number") == str(issue_number) and row.get("game_pk") == str(game_pk))
            ]
    keep.extend(records)
    keep.sort(key=lambda r: (int(r.get("issue_number") or 0), int(r.get("game_pk") or 0), r.get("pick", "")))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CLV_FIELDS)
        writer.writeheader()
        writer.writerows(keep)


def summarize_clv(records: list[dict[str, str]]) -> tuple[int, float | None]:
    values = [float(r["clv_prob"]) for r in records if r.get("clv_status") == "CLV_TRACKED"]
    return len(values), (sum(values) / len(values) if values else None)
