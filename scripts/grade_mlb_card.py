#!/usr/bin/env python3
"""Grade a finalized SportsEdge MLB card from the official MLB StatsAPI feed.

The grader is settlement-only: it never changes model probabilities or card
qualification. It reads the latest final SportsEdge card comment, settles every
ACTIONABLE row at its posted price, grades LEAN props separately, comments the
result, and upserts one row per card issue in ledger/mlb_ledger.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
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


class NoFinalCard(RuntimeError):
    """The issue exists, but its bot has not emitted a final card yet."""


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


def _request_json(
    url: str,
    *,
    token: str | None = None,
    method: str = "GET",
    payload: Any = None,
) -> Any:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "SportsEdge-MLB-Grader/1",
    }
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
    base = f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments"
    comments: list[dict[str, Any]] = []
    page_number = 1
    while True:
        page = _request_json(f"{base}?per_page=100&page={page_number}", token=token)
        comments.extend(page)
        if len(page) < 100:
            return comments
        page_number += 1


def post_github_comment(repo: str, issue_number: int, body: str, token: str) -> None:
    owner, name = repo.split("/", 1)
    _request_json(
        f"https://api.github.com/repos/{owner}/{name}/issues/{issue_number}/comments",
        token=token,
        method="POST",
        payload={"body": body},
    )


def fetch_statsapi(game_pk: int) -> dict[str, Any]:
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    last_error: BaseException | None = None
    for attempt in range(1, 4):
        try:
            return _request_json(url)
        except RuntimeError as exc:
            last_error = exc
            retryable = any(
                f"HTTP {code} " in str(exc)
                for code in (500, 502, 503, 504)
            )
            if not retryable or attempt == 3:
                break
        except urllib.error.URLError as exc:  # pragma: no cover - network diagnostic
            last_error = exc
            if attempt == 3:
                break
        time.sleep(attempt)
    raise RuntimeError(
        f"MLB_STATSAPI_UNAVAILABLE:{game_pk}:{last_error}"
    ) from last_error


def find_final_card_comment(comments: Iterable[dict[str, Any]]) -> str:
    candidates: list[str] = []
    for comment in comments:
        body = str(comment.get("body") or "")
        first_line = body.splitlines()[0] if body.splitlines() else ""
        if CARD_HEADER in body and "PRE-CONTEXT · NOT FINAL" not in first_line:
            candidates.append(body)
    if not candidates:
        raise NoFinalCard("no final SportsEdge MLB card comment found")
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
            rows.append(
                CardRow(
                    game_pk=int(cells[1]),
                    pick=cells[2],
                    price=int(cells[3]),
                    status=status,
                )
            )
        except ValueError as exc:
            raise ValueError(f"invalid card row: {line}") from exc
    if not rows:
        raise ValueError("final card contains no ACTIONABLE or LEAN rows")
    return rows


def is_final(feed: dict[str, Any]) -> bool:
    status = feed.get("gameData", {}).get("status", {})
    return status.get("abstractGameState") == "Final" or str(
        status.get("detailedState", "")
    ).startswith("Final")


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
        match = re.fullmatch(
            r"(?:f5 )?run line (away|home) ([+-]?\d+(?:\.\d+)?)", low
        )
        if match:
            side, line = match.group(1), float(match.group(2))
            margin = (away - home) if side == "away" else (home - away)
            adjusted = margin + line
            result = "P" if adjusted == 0 else ("W" if adjusted > 0 else "L")
        else:
            match = re.fullmatch(r"(?:f5 )?totals (over|under) (\d+(?:\.\d+)?)", low)
            if match:
                result = _compare(away + home, match.group(1), float(match.group(2)))
            else:
                try:
                    result = _settle_team_or_first_inning(
                        pick, low, names, away, home, feed
                    )
                except ValueError as exc:
                    if not str(exc).startswith("unsupported ACTIONABLE market:"):
                        raise
                    settled = settle_lean(row, feed)
                    if settled.result == "UNRESOLVED":
                        raise ValueError(f"unsupported ACTIONABLE market: {pick}") from exc
                    return settled
    return SettledRow(row=row, result=result, units=_units(result, row.price))


def _settle_team_or_first_inning(
    pick: str,
    low: str,
    names: dict[str, str],
    away: int,
    home: int,
    feed: dict[str, Any],
) -> str:
    for side in ("away", "home"):
        team = names[side]
        team_id = str(
            feed.get("gameData", {})
            .get("teams", {})
            .get(side, {})
            .get("id")
            or ""
        ).strip()
        aliases = [team.lower()]
        if team_id:
            aliases.append(team_id.lower())
        for alias in aliases:
            pattern = rf"{re.escape(alias)} (?:f5 )?team totals (over|under) (\d+(?:\.\d+)?)"
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
    tokens = [
        token
        for token in folded.split()
        if token not in {"jr", "sr", "ii", "iii", "iv", "v"}
    ]
    return " ".join(tokens)


def _box_players(feed: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for side in ("away", "home"):
        team_box = feed["liveData"]["boxscore"]["teams"][side]
        pitcher_ids = [int(pid) for pid in team_box.get("pitchers", [])]
        starting_pitcher_id = pitcher_ids[0] if pitcher_ids else None
        for player in team_box.get("players", {}).values():
            copy = dict(player)
            copy["_side"] = side
            person_id = (copy.get("person") or {}).get("id")
            copy["_starting_pitcher"] = (
                starting_pitcher_id is not None and int(person_id or -1) == starting_pitcher_id
            )
            out.append(copy)
    return out


def _parse_prop_pick(pick: str) -> tuple[str, str, str, float]:
    # Longest market names first so player names remain unambiguous.
    markets = [
        "Hits Walks Stolen Bases",
        "Hits Runs Stolen Bases",
        "Pitcher Hits Walks Er",
        "Pitcher Hits Allowed",
        "Hits Runs Rbis",
        "Hits Stolen Bases",
        "Extra Base Hits",
        "Stolen Bases",
        "Total Bases",
        "Pitcher Outs",
        "Pitcher K",
        "Pitcher Er",
        "Pitcher Bb",
        "Home Runs",
        "Batter Bb",
        "Batter K",
        "Runs Rbis",
        "Singles",
        "Doubles",
        "Triples",
        "Rbi",
        "Runs",
        "Hits",
    ]
    for market in markets:
        match = re.fullmatch(
            rf"(.+?) {re.escape(market)} (Over|Under) (\d+(?:\.\d+)?)",
            pick,
            re.I,
        )
        if match:
            return (
                match.group(1),
                market.lower(),
                match.group(2).lower(),
                float(match.group(3)),
            )
    raise ValueError(f"unsupported LEAN prop: {pick}")


def _is_starter(player: dict[str, Any], market: str) -> bool:
    if market.startswith("pitcher"):
        return bool(player.get("_starting_pitcher"))
    order = str(player.get("battingOrder") or "")
    # MLB boxscore starting hitters are 100, 200, ... 900. Substitutes use
    # suffixes inside the same batting-order slot (for example 901).
    return order.isdigit() and int(order) in range(100, 1000, 100)


def _prop_value(player: dict[str, Any], market: str) -> float:
    stats = player.get("stats", {})
    batting = stats.get("batting") or {}
    pitching = stats.get("pitching") or {}
    if market == "hits":
        return float(batting.get("hits") or 0)
    if market == "home runs":
        return float(batting.get("homeRuns") or 0)
    if market == "total bases":
        return float(batting.get("totalBases") or 0)
    if market == "rbi":
        return float(batting.get("rbi") or 0)
    if market == "runs":
        return float(batting.get("runs") or 0)
    if market == "stolen bases":
        return float(batting.get("stolenBases") or 0)
    if market == "batter bb":
        return float(batting.get("baseOnBalls") or 0)
    if market == "batter k":
        return float(batting.get("strikeOuts") or 0)
    if market in {"singles", "doubles", "triples", "extra base hits"}:
        hits = int(batting.get("hits") or 0)
        doubles = int(batting.get("doubles") or 0)
        triples = int(batting.get("triples") or 0)
        home_runs = int(batting.get("homeRuns") or 0)
        singles = hits - doubles - triples - home_runs
        if singles < 0:
            raise ValueError("invalid batter hit-type accounting")
        if market == "singles":
            return float(singles)
        if market == "doubles":
            return float(doubles)
        if market == "triples":
            return float(triples)
        return float(doubles + triples + home_runs)
    if market == "hits runs rbis":
        return float(
            (batting.get("hits") or 0)
            + (batting.get("runs") or 0)
            + (batting.get("rbi") or 0)
        )
    if market == "hits runs stolen bases":
        return float(
            (batting.get("hits") or 0)
            + (batting.get("runs") or 0)
            + (batting.get("stolenBases") or 0)
        )
    if market == "runs rbis":
        return float((batting.get("runs") or 0) + (batting.get("rbi") or 0))
    if market == "hits stolen bases":
        return float((batting.get("hits") or 0) + (batting.get("stolenBases") or 0))
    if market == "hits walks stolen bases":
        return float(
            (batting.get("hits") or 0)
            + (batting.get("baseOnBalls") or 0)
            + (batting.get("stolenBases") or 0)
        )
    if market == "pitcher k":
        return float(pitching.get("strikeOuts") or 0)
    if market == "pitcher hits allowed":
        return float(pitching.get("hits") or 0)
    if market == "pitcher er":
        return float(pitching.get("earnedRuns") or 0)
    if market == "pitcher bb":
        return float(pitching.get("baseOnBalls") or 0)
    if market == "pitcher hits walks er":
        return float(
            (pitching.get("hits") or 0)
            + (pitching.get("baseOnBalls") or 0)
            + (pitching.get("earnedRuns") or 0)
        )
    if market == "pitcher outs":
        ip = str(pitching.get("inningsPitched") or "0.0")
        whole, frac = ip.split(".", 1)
        return float(int(whole) * 3 + int(frac[0]))
    raise ValueError(f"unsupported prop market: {market}")


def settle_lean(row: CardRow, feed: dict[str, Any]) -> SettledRow:
    record_win = re.fullmatch(
        r"(.+?) Pitcher Record Win (Yes|No)(?: 0(?:\.0+)?)?",
        row.pick,
        re.I,
    )
    if record_win:
        player_name = record_win.group(1)
        side = record_win.group(2).lower()
        matches = [
            player
            for player in _box_players(feed)
            if _norm_name(str((player.get("person") or {}).get("fullName") or ""))
            == _norm_name(player_name)
        ]
        if len(matches) != 1 or not _is_starter(matches[0], "pitcher record win"):
            return SettledRow(row=row, result="VOID", units=0.0)
        winner = (feed.get("liveData", {}).get("decisions", {}) or {}).get("winner") or {}
        winner_id = winner.get("id")
        player_id = (matches[0].get("person") or {}).get("id")
        if winner_id is None and not str(winner.get("fullName") or "").strip():
            return SettledRow(row=row, result="UNRESOLVED", units=0.0)
        won = (
            winner_id is not None
            and player_id is not None
            and int(winner_id) == int(player_id)
        ) or (
            _norm_name(str(winner.get("fullName") or ""))
            == _norm_name(player_name)
        )
        result = "W" if (won == (side == "yes")) else "L"
        return SettledRow(row=row, result=result, units=_units(result, row.price))

    try:
        player_name, market, direction, line = _parse_prop_pick(row.pick)
    except ValueError as exc:
        if str(exc).startswith("unsupported LEAN prop:"):
            return SettledRow(row=row, result="UNRESOLVED", units=0.0)
        raise
    matches = [
        player
        for player in _box_players(feed)
        if _norm_name(str((player.get("person") or {}).get("fullName") or ""))
        == _norm_name(player_name)
    ]
    if len(matches) != 1 or not _is_starter(matches[0], market):
        return SettledRow(row=row, result="VOID", units=0.0)
    result = _compare(_prop_value(matches[0], market), direction, line)
    return SettledRow(row=row, result=result, units=_units(result, row.price))


def summarize(rows: list[SettledRow]) -> tuple[int, int, int, float, float]:
    wins = sum(row.result == "W" for row in rows)
    losses = sum(row.result == "L" for row in rows)
    pushes = sum(row.result == "P" for row in rows)
    net = sum(row.units for row in rows)
    roi = (net / len(rows) * 100.0) if rows else 0.0
    return wins, losses, pushes, net, roi


def render_comment(
    issue_number: int,
    feed: dict[str, Any],
    main: list[SettledRow],
    leans: list[SettledRow],
) -> str:
    names = _team_names(feed)
    away, home = _runs(feed, "away"), _runs(feed, "home")
    wins, losses, pushes, net, roi = summarize(main)
    lines = [
        GRADE_MARKER.format(issue=issue_number),
        f"## MLB graded result — {names['away']} @ {names['home']} ({away}-{home})",
        "",
        "### ACTIONABLE — main ledger",
        "| Play | Price | Result | Units |",
        "|---|---:|:---:|---:|",
    ]
    for item in main:
        lines.append(
            f"| {item.row.pick} | {item.row.price:+d} | {item.result} | {item.units:+.2f}u |"
        )
    lines += [
        "",
        f"**Record:** {wins}-{losses}-{pushes} · **Net:** {net:+.2f}u · **ROI:** {roi:+.1f}%",
    ]
    if leans:
        lines += [
            "",
            "### LEAN props — separate, not included above",
            "| Play | Price | Result | Units |",
            "|---|---:|:---:|---:|",
        ]
        for item in leans:
            lines.append(
                f"| {item.row.pick} | {item.row.price:+d} | {item.result} | {item.units:+.2f}u |"
            )
        lean_wins = sum(row.result == "W" for row in leans)
        lean_losses = sum(row.result == "L" for row in leans)
        lean_pushes = sum(row.result == "P" for row in leans)
        lean_voids = sum(row.result == "VOID" for row in leans)
        lean_unresolved = sum(row.result == "UNRESOLVED" for row in leans)
        lean_net = sum(row.units for row in leans)
        lines += [
            "",
            f"LEAN record: {lean_wins}-{lean_losses}-{lean_pushes}, "
            f"{lean_voids} void, {lean_unresolved} unresolved · "
            f"net {lean_net:+.2f}u (not main ledger).",
        ]
    lines += [
        "",
        "Settlement source: MLB StatsAPI final box score + linescore. "
        "Posted card prices only; no closing-price substitution.",
    ]
    return "\n".join(lines)


def _ledger_row(
    issue_number: int,
    feed: dict[str, Any],
    main: list[SettledRow],
    *,
    graded_at_utc: str,
) -> dict[str, str]:
    wins, losses, pushes, net, roi = summarize(main)
    names = _team_names(feed)
    away_runs, home_runs = _runs(feed, "away"), _runs(feed, "home")
    return {
        "date": str(
            feed.get("gameData", {}).get("datetime", {}).get("officialDate") or ""
        ),
        "issue_number": str(issue_number),
        "game_pk": str(main[0].row.game_pk if main else ""),
        "away": names["away"],
        "home": names["home"],
        "final_score": f"{away_runs}-{home_runs}",
        "wins": str(wins),
        "losses": str(losses),
        "pushes": str(pushes),
        "net_units": f"{net:.4f}",
        "roi_pct": f"{roi:.2f}",
        "graded_at_utc": graded_at_utc,
    }


def upsert_ledger(
    path: Path,
    issue_number: int,
    feed: dict[str, Any],
    main: list[SettledRow],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "issue_number",
        "game_pk",
        "away",
        "home",
        "final_score",
        "wins",
        "losses",
        "pushes",
        "net_units",
        "roi_pct",
        "graded_at_utc",
    ]
    other_rows: list[dict[str, str]] = []
    prior: dict[str, str] | None = None
    target_game_pk = str(main[0].row.game_pk if main else "")
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                same_key = (
                    row.get("issue_number") == str(issue_number)
                    and row.get("game_pk") == target_game_pk
                )
                if same_key:
                    prior = row
                else:
                    other_rows.append(row)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    candidate = _ledger_row(issue_number, feed, main, graded_at_utc=now)
    if prior is not None:
        comparable_fields = [field for field in fieldnames if field != "graded_at_utc"]
        unchanged = all(prior.get(field, "") == candidate[field] for field in comparable_fields)
        if unchanged:
            candidate["graded_at_utc"] = prior.get("graded_at_utc", "") or now

    other_rows.append(candidate)
    other_rows.sort(
        key=lambda row: (
            row.get("date", ""),
            int(row.get("issue_number") or 0),
            int(row.get("game_pk") or 0),
        )
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(other_rows)


def grade_issue(
    issue_number: int,
    *,
    repo: str = DEFAULT_REPO,
    token: str | None = None,
    ledger_path: Path = DEFAULT_LEDGER,
    comments: list[dict[str, Any]] | None = None,
    feed: dict[str, Any] | None = None,
    feeds: dict[int, dict[str, Any]] | None = None,
    post_comment: bool = True,
    force_comment: bool = False,
) -> str:
    token = token or os.environ.get("GITHUB_TOKEN")
    if comments is None:
        if not token:
            raise RuntimeError("GITHUB_TOKEN is required to read issue comments")
        comments = github_comments(repo, issue_number, token)

    try:
        card = find_final_card_comment(comments)
    except NoFinalCard:
        return "SKIP_NO_FINAL_CARD"

    try:
        rows = parse_card_rows(card)
    except ValueError as exc:
        if str(exc) == "final card contains no ACTIONABLE or LEAN rows":
            return "SKIP_NO_GRADEABLE_ROWS"
        raise
    game_pks = sorted({row.game_pk for row in rows})
    if feed is not None and feeds is not None:
        raise ValueError("provide feed or feeds, not both")
    if feed is not None and len(game_pks) != 1:
        raise ValueError("single feed cannot settle a multi-game card")

    feed_by_game: dict[int, dict[str, Any]] = {}
    if feeds is not None:
        missing = [game_pk for game_pk in game_pks if game_pk not in feeds]
        if missing:
            raise ValueError(f"missing feeds for game_pks: {missing}")
        feed_by_game = {game_pk: feeds[game_pk] for game_pk in game_pks}
    elif feed is not None:
        feed_by_game[game_pks[0]] = feed
    else:
        for game_pk in game_pks:
            try:
                feed_by_game[game_pk] = fetch_statsapi(game_pk)
            except RuntimeError:
                return f"SKIP_SOURCE_UNAVAILABLE:{game_pk}"

    if any(not is_final(feed_by_game[game_pk]) for game_pk in game_pks):
        return "SKIP_NOT_FINAL"

    rendered_games: list[str] = []
    for index, game_pk in enumerate(game_pks):
        game_feed = feed_by_game[game_pk]
        game_rows = [row for row in rows if row.game_pk == game_pk]
        main = [
            settle_actionable(row, game_feed)
            for row in game_rows
            if row.status == "ACTIONABLE"
        ]
        leans = [
            settle_lean(row, game_feed)
            for row in game_rows
            if row.status == "LEAN"
        ]
        rendered = render_comment(issue_number, game_feed, main, leans)
        if index:
            marker_line = GRADE_MARKER.format(issue=issue_number) + "\n"
            if rendered.startswith(marker_line):
                rendered = rendered[len(marker_line):]
        rendered_games.append(rendered)
        if main:
            upsert_ledger(ledger_path, issue_number, game_feed, main)

    body = "\n\n---\n\n".join(rendered_games)
    marker = GRADE_MARKER.format(issue=issue_number)
    already_commented = any(
        marker in str(comment.get("body") or "") for comment in comments
    )
    if post_comment and (force_comment or not already_commented):
        if not token:
            raise RuntimeError("GITHUB_TOKEN is required to post grade comment")
        post_github_comment(repo, issue_number, body, token)
    return body


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_number", type=int)
    parser.add_argument(
        "--repo", default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--no-comment", action="store_true")
    parser.add_argument("--force-comment", action="store_true")
    args = parser.parse_args(argv)
    result = grade_issue(
        args.issue_number,
        repo=args.repo,
        ledger_path=args.ledger,
        post_comment=not args.no_comment,
        force_comment=args.force_comment,
    )
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
