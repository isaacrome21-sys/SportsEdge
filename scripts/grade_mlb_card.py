#!/usr/bin/env python3
"""Grade a finalized SportsEdge MLB card from the official MLB StatsAPI feed.

The grader is deliberately settlement-only: it never changes model probabilities or
card qualification. It reads the latest final SportsEdge card comment, settles every
ACTIONABLE row at its posted price, grades LEAN props separately, comments the result,
and upserts one row per card issue in ledger/mlb_ledger.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

GRADE_MARKER = "<!-- sportsedge-mlb-auto-grade:v1 issue={issue} -->"
DEFAULT_REPO = "isaacrome21-sys/SportsEdge"
DEFAULT_LEDGER = Path("ledger/mlb_ledger.csv")
CARD_HEADER = "# SportsEdge MLB card ("


@dataclass(frozen=True)
class CardRow:
    game_pk: int
    pick: str
    price: int
    status: str


@dataclass(frozen=True)
class SettledRow:
    row: CardRow
    result: str
    units: float


def _request_json(url: str, *, token: str | None = None, method: str = "GET", payload: Any = None) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "SportsEdge-MLB-Grader/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:  # pragma: no cover - network diagnostic
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {detail}") from exc


def github_comments(repo: str, issue_number: int, token: str) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    url = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments?per_page=100"
    comments: list[dict[str, Any]] = []
    while url:
        page = _request_json(url, token=token)
        comments.extend(page)
        if len(page) < 100:
            break
        url = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments?per_page=100&page={len(comments)//100 + 1}"
    return comments


def post_github_comment(repo: str, issue_number: int, body: str, token: str) -> None:
    owner, name = repo.split("/", 1)
    _request_json(
        f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments",
        token=token,
        method="POST",
        payload={"body": body},
    )


def fetch_statsapi(game_pk: int) -> dict[str, Any]:
    return _request_json(f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live")


def find_final_card_comment(comments: Iterable[dict[str, Any]]) -> str:
    candidates = []
    for comment in comments:
        body = str(comment.get("body") or "")
        if CARD_HEADER in body and "PRE-CONTEXT · NOT FINAL" not in body.splitlines()[0]:
            candidates.append(body)
    if not candidates:
        raise ValueError("no final SportsEdge MLB card comment found")
    return candidates[-1]


def parse_card_rows(body: str) -> list[CardRow]:
    rows: list[CardRow] = []
    for line in body.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 12 or not cells[0].isdigit():
            continue
        status = cells[11]
        if status not in {"ACTIONABLE", "LEAN"}:
            continue
        try:
            rows.append(CardRow(game_pk=int(cells[1]), pick=cells[2], price=int(cells[3]), status=status))
        except ValueError as exc:
            raise ValueError(f"invalid card row: {line}") from exc
    if not rows:
        raise ValueError("final card contains no ACTIONABLE or LEAN rows")
    game_pks = {row.game_pk for row in rows}
    if len(game_pks) != 1:
        raise ValueError(f"card spans multiple game_pks: {sorted(game_pks)}")
    return rows


def is_final(feed: dict[str, Any]) -> bool:
    status = feed.get("gameData", {}).get("status", {})
    return status.get("abstractGameState") == "Final" or str(status.get("detailedState", "")).startswith("Final")


def _runs(feed: dict[str, Any], side: str, innings: int | None = None) -> int:
    if innings is None:
        return int(feed["liveData"]["linescore"]["teams"][side]["runs"])
    total = 0
    for inning in feed["liveData"]["linescore"].get("innings", [])[:innings]:
        total += int((inning.get(side) or {}).get("runs") or 0)
    return total


def _american_win_units(price: int) -> float:
    return price / 100.0 if price > 0 else 100.0 / abs(price)


def _compare(value: float, direction: str, line: float) -> str:
    if value == line:
        return "P"
    won = value > line if direction == "over" else value < line
    return "W" if won else "L"


def _units(result: str, price: int) -> float:
    if result == "W":
        return _american_win_units(price)
    if result == "L":
        return -1.0
    return 0.0


def _team_names(feed: dict[str, Any]) -> dict[str, str]:
    teams = feed["gameData"]["teams"]
    return {"away": teams["away"]["name"], "home": teams["home"]["name"]}


def settle_actionable(row: CardRow, feed: dict[str, Any]) -> SettledRow:
    pick = row.pick.strip()
    low = pick.lower()
    names = _team_names(feed)
    f5 = low.startswith("f5 ") or " f5 " in low
    away = _runs(feed, "away", 5 if f5 else None)
    home = _runs(feed, "home", 5 if f5 else None)

    if low in {"moneyline away", "f5 moneyline away"}:
        result = "P" if away == home else ("W" if away > home else "L")
    elif low in {"moneyline home", "f5 moneyline home"}:
        result = "P" if home == away else ("W" if home > away else "L")
    else:
        match = re.fullmatch(r"(?:f5 )?run line (away|home) ([+-]?\d+(?:\.\d+)?)", low)
        if match:
            side, line = match.group(1), float(match.group(2))
            margin = (away - home) if side == "away" else (home - away)
            result = _compare(margin, "over", -line) if False else ("P" if margin + line == 0 else ("W" if margin + line > 0 else "L"))
        else:
            match = re.fullmatch(r"(?:f5 )?totals (over|under) (\d+(?:\.\d+)?)", low)
            if match:
                result = _compare(away + home, match.group(1), float(match.group(2)))
            else:
                result = _settle_team_or_first_inning(pick, low, names, away, home, feed, f5)
    return SettledRow(row=row, result=result, units=_units(result, row.price))


def _settle_team_or_first_inning(
    pick: str,
    low: str,
    names: dict[str, str],
    away: int,
    home: int,
    feed: dict[str, Any],
    f5: bool,
) -> str:
    for side in ("away", "home"):
        team = names[side]
        pattern = rf"{re.escape(team.lower())} (?:f5 )?team totals (over|under) (\d+(?:\.\d+)?)"
        match = re.fullmatch(pattern, low)
        if match:
            value = away if side == "away" else home
            return _compare(value, match.group(1), float(match.group(2)))

    first_inning_runs = _runs(feed, "away", 1) + _runs(feed, "home", 1)
    has_run = first_inning_runs > 0
    if low in {"yrfi yes", "yrfi"}:
        return "W" if has_run else "L"
    if low in {"yrfi no", "nrfi yes", "nrfi"}:
        return "W" if not has_run else "L"
    if low == "nrfi no":
        return "W" if has_run else "L"
    raise ValueError(f"unsupported ACTIONABLE market: {pick}")


def _norm_name(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch)).lower()
    folded = re.sub(r"[^a-z0-9 ]+", " ", folded)
    tokens = [t for t in folded.split() if t not in {"jr", "sr", "ii", "iii", "iv", "v"}]
    return " ".join(tokens)


def _box_players(feed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for side in ("away", "home"):
        team_box = feed["liveData"]["boxscore"]["teams"][side]
        for player in team_box.get("players", {}).values():
            copy = dict(player)
            copy["_side"] = side
            out.append(copy)
    return out


def _parse_prop_pick(pick: str) -> tuple[str, str, str, float]:
    # Longest market names first so player names remain unambiguous.
    markets = [
        "Pitcher Hits Walks Er", "Pitcher Hits Allowed", "Hits Runs Rbis",
        "Total Bases", "Pitcher Outs", "Pitcher K", "Pitcher Er",
        "Pitcher Bb", "Batter Bb", "Rbi", "Hits",
    ]
    for market in markets:
        match = re.fullmatch(rf"(.+?) {re.escape(market)} (Over|Under) (\d+(?:\.\d+)?)", pick, re.I)
        if match:
            return match.group(1), market.lower(), match.group(2).lower(), float(match.group(3))
    raise ValueError(f"unsupported LEAN prop: {pick}")


def _is_starter(player: dict[str, Any], market: str) -> bool:
    stats = player.get("stats", {})
    if market.startswith("pitcher"):
        return int((stats.get("pitching") or {}).get("gamesStarted") or 0) == 1
    order = str(player.get("battingOrder") or "")
    return order.isdigit() and int(order) % 100 == 0


def _prop_value(player: dict[str, Any], market: str) -> float:
    stats = player.get("stats", {})
    batting = stats.get("batting") or {}
    pitching = stats.get("pitching") or {}
    if market == "hits":
        return float(batting.get("hits") or 0)
    if market == "total bases":
        return float(batting.get("totalBases") or 0)
    if market == "rbi":
        return float(batting.get("rbi") or 0)
    if market == "hits runs rbis":
        return float((batting.get("hits") or 0) + (batting.get("runs") or 0) + (batting.get("rbi") or 0))
    if market == "batter bb":
        return float(batting.get("baseOnBalls") or 0)
    if market == "pitcher k":
        return float(pitching.get("strikeOuts") or 0)
    if market == "pitcher hits allowed":
        return float(pitching.get("hits") or 0)
    if market == "pitcher er":
        return float(pitching.get("earnedRuns") or 0)
    if market == "pitcher bb":
        return float(pitching.get("baseOnBalls") or 0)
    if market == "pitcher hits walks er":
        return float((pitching.get("hits") or 0) + (pitching.get("baseOnBalls") or 0) + (pitching.get("earnedRuns") or 0))
    if market == "pitcher outs":
        ip = str(pitching.get("inningsPitched") or "0.0")
        whole, frac = ip.split(".", 1)
        return float(int(whole) * 3 + int(frac[0]))
    raise ValueError(f"unsupported prop market: {market}")


def settle_lean(row: CardRow, feed: dict[str, Any]) -> SettledRow:
    player_name, market, direction, line = _parse_prop_pick(row.pick)
    matches = [p for p in _box_players(feed) if _norm_name(str((p.get("person") or {}).get("fullName") or "")) == _norm_name(player_name)]
    if len(matches) != 1 or not _is_starter(matches[0], market):
        return SettledRow(row=row, result="VOID", units=0.0)
    result = _compare(_prop_value(matches[0], market), direction, line)
    return SettledRow(row=row, result=result, units=_units(result, row.price))


def summarize(rows: list[SettledRow]) -> tuple[int, int, int, float, float]:
    wins = sum(r.result == "W" for r in rows)
    losses = sum(r.result == "L" for r in rows)
    pushes = sum(r.result == "P" for r in rows)
    net = sum(r.units for r in rows)
    roi = (net / len(rows) * 100.0) if rows else 0.0
    return wins, losses, pushes, net, roi


def render_comment(issue_number: int, feed: dict[str, Any], main: list[SettledRow], leans: list[SettledRow]) -> str:
    names = _team_names(feed)
    away, home = _runs(feed, "away"), _runs(feed, "home")
    w, l, p, net, roi = summarize(main)
    lines = [
        GRADE_MARKER.format(issue=issue_number),
        f"## MLB graded result — {names['away']} @ {names['home']} ({away}-{home})",
        "",
        "### ACTIONABLE — main ledger",
        "| Play | Price | Result | Units |",
        "|---|---:|:---:|---:|",
    ]
    for item in main:
        lines.append(f"| {item.row.pick} | {item.row.price:+d} | {item.result} | {item.units:+.2f}u |")
    lines += ["", f"**Record:** {w}-{l}-{p} · **Net:** {net:+.2f}u · **ROI:** {roi:+.1f}%"]
    if leans:
        lines += ["", "### LEAN props — separate, not included above", "| Play | Price | Result | Units |", "|---|---:|:---:|---:|"]
        for item in leans:
            lines.append(f"| {item.row.pick} | {item.row.price:+d} | {item.result} | {item.units:+.2f}u |")
        lw = sum(r.result == "W" for r in leans)
        ll = sum(r.result == "L" for r in leans)
        lp = sum(r.result == "P" for r in leans)
        lv = sum(r.result == "VOID" for r in leans)
        lnet = sum(r.units for r in leans)
        lines += ["", f"LEAN record: {lw}-{ll}-{lp}, {lv} void · net {lnet:+.2f}u (not main ledger)."]
    lines += ["", "Settlement source: MLB StatsAPI final box score + linescore. Posted card prices only; no closing-price substitution."]
    return "\n".join(lines)


def upsert_ledger(path: Path, issue_number: int, feed: dict[str, Any], main: list[SettledRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date", "issue_number", "game_pk", "away", "home", "final_score",
        "wins", "losses", "pushes", "net_units", "roi_pct", "graded_at_utc",
    ]
    existing: list[dict[str, str]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            existing = [row for row in csv.DictReader(handle) if row.get("issue_number") != str(issue_number)]
    w, l, p, net, roi = summarize(main)
    names = _team_names(feed)
    away_runs, home_runs = _runs(feed, "away"), _runs(feed, "home")
    existing.append({
        "date": str(feed.get("gameData", {}).get("datetime", {}).get("officialDate") or ""),
        "issue_number": str(issue_number),
        "game_pk": str(main[0].row.game_pk if main else ""),
        "away": names["away"], "home": names["home"],
        "final_score": f"{away_runs}-{home_runs}", "wins": str(w), "losses": str(l), "pushes": str(p),
        "net_units": f"{net:.4f}", "roi_pct": f"{roi:.2f}",
        "graded_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    })
    existing.sort(key=lambda row: (row.get("date", ""), int(row.get("issue_number") or 0)))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader(); writer.writerows(existing)


def grade_issue(
    issue_number: int,
    *,
    repo: str = DEFAULT_REPO,
    token: str | None = None,
    ledger_path: Path = DEFAULT_LEDGER,
    comments: list[dict[str, Any]] | None = None,
    feed: dict[str, Any] | None = None,
    post_comment: bool = True,
    force_comment: bool = False,
) -> str:
    token = token or os.environ.get("GITHUB_TOKEN")
    if comments is None:
        if not token:
            raise RuntimeError("GITHUB_TOKEN is required to read issue comments")
        comments = github_comments(repo, issue_number, token)
    card = find_final_card_comment(comments)
    rows = parse_card_rows(card)
    game_pk = rows[0].game_pk
    feed = feed or fetch_statsapi(game_pk)
    if not is_final(feed):
        return "SKIP_NOT_FINAL"

    main = [settle_actionable(row, feed) for row in rows if row.status == "ACTIONABLE"]
    leans = [settle_lean(row, feed) for row in rows if row.status == "LEAN"]
    if not main:
        raise ValueError("final card has no ACTIONABLE rows")
    body = render_comment(issue_number, feed, main, leans)
    upsert_ledger(ledger_path, issue_number, feed, main)

    marker = GRADE_MARKER.format(issue=issue_number)
    already_commented = any(marker in str(comment.get("body") or "") for comment in comments)
    if post_comment and (force_comment or not already_commented):
        if not token:
            raise RuntimeError("GITHUB_TOKEN is required to post grade comment")
        post_github_comment(repo, issue_number, body, token)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_number", type=int)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO))
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--no-comment", action="store_true")
    parser.add_argument("--force-comment", action="store_true")
    args = parser.parse_args(argv)
    result = grade_issue(
        args.issue_number, repo=args.repo, ledger_path=args.ledger,
        post_comment=not args.no_comment, force_comment=args.force_comment,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
