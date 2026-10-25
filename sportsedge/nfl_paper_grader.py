"""Strict NFL PAPER capture, settlement and paired no-vig CLV.

Only actual frozen-engine research leans are tracked, never promoted. Every
unavailable quote, score or prop statistic fails closed without invented data.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sportsedge.line_snapshots import (
    SNAPSHOT_ROOT, append_snapshot, build_snapshot, entry_and_close,
)
from sportsedge.nfl_lines_intake import parse_nfl_lines
from sportsedge.pipeline.grading import (
    FinalResult, GradeError, grade, no_vig_clv, units,
)


class NflPaperError(ValueError):
    pass


def _time(value: str | None) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NflPaperError("NFL_TIME_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise NflPaperError("NFL_TIME_OFFSET_REQUIRED")
    return dt


def _exact_engine_price(value: Any) -> int:
    """Never silently truncate an engine quote to an American integer."""
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?[0-9]+", value.strip()):
        return int(value.strip())
    raise NflPaperError("NFL_ENGINE_PRICE_NOT_EXACT_INTEGER")


def _side_line(market: str, line: Any, selection: str) -> float | None:
    if line is None:
        return None
    value = float(line)
    return -value if market == "spread" and selection == "HOME" else value


def _key(away: str, home: str, market: str, subject: str,
         selection: str, line: float | None) -> str:
    suffix = "" if line is None else f"{line:g}"
    return f"{away}@{home}|{market}|{subject}|{selection}|{suffix}"


def _selection(raw: Any, market: str, away: str, home: str) -> str:
    value = str(raw or "").upper()
    if market in {"moneyline", "spread"}:
        if value in {"AWAY", away.upper()}:
            return "AWAY"
        if value in {"HOME", home.upper()}:
            return "HOME"
    elif value in {"OVER", "UNDER"}:
        return value
    raise NflPaperError("NFL_PICK_SELECTION_UNSUPPORTED")


def capture_nfl_issue(*, body: str, title: str, issue_number: int,
                      game_start: str, recorded_at: str, engine: dict | None = None,
                      root: Path = SNAPSHOT_ROOT) -> dict:
    """Append a real captured DK game without issue-time fallback or fake picks."""
    tickets = parse_nfl_lines(body, title=title)
    if len(tickets) != 1:
        raise NflPaperError("NFL_ONE_GAME_PER_SNAPSHOT_REQUIRED")
    ticket = tickets[0]
    start, captured, recorded = (
        _time(game_start), _time(ticket.captured_at), _time(recorded_at)
    )
    if not (captured < start and recorded < start):
        raise NflPaperError("NFL_NOT_RECORDED_PREKICKOFF")
    if captured > recorded:
        raise NflPaperError("NFL_CAPTURE_FUTURE_OR_BACKDATED")
    # Actual bookmaker capture is independent from relay/record time. The
    # owner-approved quote-age limit is inclusive at exactly 1800 seconds.
    if (recorded - captured).total_seconds() > 1800:
        raise NflPaperError("NFL_CAPTURE_STALE_OVER_1800S")

    games = (engine or {}).get("games") or []
    if engine is not None and (
        len(games) != 1
        or games[0].get("away") != ticket.away
        or games[0].get("home") != ticket.home
        or _time(games[0].get("commence_time")) != start
    ):
        raise NflPaperError("NFL_INDEPENDENT_SCHEDULE_MISMATCH")

    board = [
        dict(market=m.market, line=m.line, team=m.team, player=m.player,
             price_a=m.away_or_over_price, price_b=m.home_or_under_price)
        for m in ticket.markets
    ]
    picks = []
    for row in (games[0].get("markets") or []) if games else []:
        chosen = row.get("lean") or row.get("pick")
        if not isinstance(chosen, dict):
            continue
        market = str(row.get("market") or "").lower()
        selection = _selection(chosen.get("selection"), market, ticket.away, ticket.home)
        matches = [
            m for m in board
            if m["market"] == market
            and m["player"] == row.get("player")
            and m["team"] == row.get("team")
        ]
        if len(matches) != 1:
            raise NflPaperError("NFL_PICK_AMBIGUOUS_BOARD_PAIR")
        matched = matches[0]
        first = selection in {"AWAY", "OVER"}
        price = matched["price_a"] if first else matched["price_b"]
        opposite = matched["price_b"] if first else matched["price_a"]
        if _exact_engine_price(chosen.get("price_american")) != price:
            raise NflPaperError("NFL_PICK_PRICE_DIFFERS_FROM_CAPTURE")
        line = _side_line(market, matched["line"], selection)
        chosen_line = chosen.get("line")
        if chosen_line is not None:
            try:
                model_line = float(chosen_line)
            except (TypeError, ValueError, OverflowError) as exc:
                raise NflPaperError("NFL_PICK_LINE_INVALID") from exc
            if isinstance(chosen_line, bool) or not math.isfinite(model_line):
                raise NflPaperError("NFL_PICK_LINE_INVALID")
            if line is None or model_line != line:
                raise NflPaperError("NFL_PICK_LINE_DIFFERS_FROM_CAPTURE")
        subject = str(matched.get("player") or matched.get("team") or "")
        picks.append(dict(
            pick=_key(ticket.away, ticket.home, market, subject, selection, line),
            market=market, selection=selection, line=line, subject=subject,
            team=matched.get("team"), price=price, opposite_price=opposite,
            status="PAPER",
        ))

    snap = build_snapshot(
        sport="nfl", issue_number=issue_number, body=body, title=title,
        game=dict(away=ticket.away, home=ticket.home, start=start.isoformat(),
                  kickoff_source="INDEPENDENT_SCHEDULE"),
        board=board, picks=picks, recorded_at=recorded_at,
    )
    append_snapshot(snap, root)
    return snap


def _validate_snapshot(snap: dict) -> None:
    """Re-check stored hash and re-derive its board from preserved issue text.

    load_snapshots currently returns unverified JSON; no persisted quote or
    stake evidence may rely on caller-modified board/pick fields.
    """
    core = {k: snap.get(k) for k in ("game", "captured_at", "board", "picks", "body")}
    digest = hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()
    if snap.get("content_sha256") != digest:
        raise NflPaperError("NFL_SNAPSHOT_DIGEST_MISMATCH")
    if snap.get("sport") != "nfl":
        raise NflPaperError("NFL_SNAPSHOT_WRONG_SPORT")
    tickets = parse_nfl_lines(snap.get("body", ""), title=snap.get("title"))
    if len(tickets) != 1:
        raise NflPaperError("NFL_SNAPSHOT_GAME_AMBIGUOUS")
    ticket = tickets[0]
    game = snap.get("game") or {}
    if (game.get("away"), game.get("home")) != (ticket.away, ticket.home):
        raise NflPaperError("NFL_SNAPSHOT_GAME_MISMATCH")
    if _time(snap.get("captured_at")) != _time(ticket.captured_at):
        raise NflPaperError("NFL_SNAPSHOT_CAPTURE_MISMATCH")
    captured, recorded, start = (
        _time(snap.get("captured_at")),
        _time(snap.get("recorded_at")),
        _time(game.get("start")),
    )
    if not (captured <= recorded < start and captured < start):
        raise NflPaperError("NFL_SNAPSHOT_NOT_RECORDED_PREKICKOFF")
    if (recorded - captured).total_seconds() > 1800:
        raise NflPaperError("NFL_SNAPSHOT_CAPTURE_STALE_OVER_1800S")
    board = [
        dict(market=m.market, line=m.line, team=m.team, player=m.player,
             price_a=m.away_or_over_price, price_b=m.home_or_under_price)
        for m in ticket.markets
    ]
    if snap.get("board") != board:
        raise NflPaperError("NFL_SNAPSHOT_BOARD_MISMATCH")
    for pick in snap.get("picks") or []:
        if pick.get("status") != "PAPER":
            raise NflPaperError("NFL_SNAPSHOT_NONPAPER_PICK")
        matches = [r for r in board if r["market"] == pick.get("market")
                   and r.get("player") == pick.get("player")
                   and r.get("team") == pick.get("team")]
        # Stored picks may use subject instead of player; price/selection must
        # still bind to exactly one preserved two-sided quote for the market.
        if len(matches) != 1:
            matches = [r for r in board if r["market"] == pick.get("market")
                       and str(r.get("player") or r.get("team") or "") == pick.get("subject", "")]
        if len(matches) != 1:
            raise NflPaperError("NFL_SNAPSHOT_PICK_QUOTE_AMBIGUOUS")
        quote = matches[0]
        side = pick.get("selection")
        if side not in ("AWAY", "HOME", "OVER", "UNDER"):
            raise NflPaperError("NFL_SNAPSHOT_PICK_SIDE_INVALID")
        first = side in ("AWAY", "OVER")
        expected = quote["price_a"] if first else quote["price_b"]
        opposite = quote["price_b"] if first else quote["price_a"]
        expected_line = _side_line(pick["market"], quote["line"], side)
        if (type(pick.get("price")) is not int or pick["price"] != expected
                or type(pick.get("opposite_price")) is not int
                or pick["opposite_price"] != opposite
                or pick.get("line") != expected_line):
            raise NflPaperError("NFL_SNAPSHOT_PICK_PRICE_OR_LINE_MISMATCH")
        # A caller cannot re-key a priced selection by recomputing the
        # unkeyed snapshot digest. Re-derive its canonical identity.
        expected_subject = str(quote.get("player") or quote.get("team") or "")
        if pick.get("subject") != expected_subject:
            raise NflPaperError("NFL_SNAPSHOT_PICK_SUBJECT_MISMATCH")
        expected_key = _key(
            ticket.away, ticket.home, pick["market"],
            expected_subject, side, expected_line,
        )
        if pick.get("pick") != expected_key:
            raise NflPaperError("NFL_SNAPSHOT_PICK_KEY_MISMATCH")


def grade_nfl_issue(snapshots: list[dict], final: dict) -> list[dict]:
    """Paper settlement; numeric CLV only from distinct eligible captured pairs."""
    if not snapshots:
        return []
    for snapshot in snapshots:
        _validate_snapshot(snapshot)
    if not (
        str(final.get("url", "")).startswith("https://")
        and re.fullmatch(r"[0-9a-fA-F]{64}", str(final.get("sha256", "")))
        and final.get("fetched_at")
    ):
        raise NflPaperError("NFL_FINAL_RECEIPT_REQUIRED")
    _time(final["fetched_at"])
    away_points, home_points = final.get("away_points"), final.get("home_points")
    if any(type(x) not in (int, float) or not math.isfinite(x)
           or x < 0 or x != int(x) for x in (away_points, home_points)):
        raise NflPaperError("NFL_FINAL_SCORES_INVALID")
    rows, seen = [], set()
    for snap in snapshots:
        game = snap.get("game") or {}
        start = game.get("start")
        if not start or game.get("away") != final.get("away") or game.get("home") != final.get("home"):
            continue
        if _time(final["fetched_at"]) <= _time(start):
            raise NflPaperError("NFL_FINAL_RECEIPT_PREKICKOFF")
        same_game = [
            s for s in snapshots
            if (s.get("game") or {}).get("away") == game["away"]
            and (s.get("game") or {}).get("home") == game["home"]
            and (s.get("game") or {}).get("start") == start
        ]
        for pick in snap.get("picks") or []:
            ident = pick["pick"]
            if ident in seen:
                continue
            seen.add(ident)
            pair = entry_and_close(same_game, ident, start)
            record = dict(
                pick=ident, market=pick["market"], status="PAPER",
                result="NO_VALID_ENTRY", units=None, clv_status=pair.status,
                clv_prob=None, ladder_status="PAPER",
            )
            if pair.entry is None or pair.entry_pick is None:
                rows.append(record)
                continue
            entry_pick = pair.entry_pick
            family = entry_pick["market"]
            if family not in {"moneyline", "spread", "total"}:
                record["result"] = "NO_FINAL_STAT_OR_ENGINE"
            else:
                record["result"] = grade(
                    entry_pick,
                    FinalResult(away_score=away_points, home_score=home_points),
                    family=family,
                )
                record["units"] = units(record["result"], int(entry_pick["price"]))
            if pair.status != "OK" or pair.close is None:
                rows.append(record)
                continue
            candidates = [
                m for m in pair.close.get("board", [])
                if m.get("market") == family
                and str(m.get("player") or m.get("team") or "") == entry_pick.get("subject", "")
            ]
            if len(candidates) != 1:
                record["clv_status"] = "NO_UNAMBIGUOUS_CLOSE_PAIR"
                rows.append(record)
                continue
            close = candidates[0]
            first = entry_pick["selection"] in {"AWAY", "OVER"}
            close_price = int(close["price_a"] if first else close["price_b"])
            opposite = int(close["price_b"] if first else close["price_a"])
            close_line = _side_line(family, close.get("line"), entry_pick["selection"])
            try:
                record["clv_prob"] = no_vig_clv(
                    int(entry_pick["price"]), int(entry_pick["opposite_price"]),
                    close_price, opposite,
                    entry_line=entry_pick.get("line"), close_line=close_line,
                )
                record["clv_status"] = "CLV_TRACKED_PAPER"
            except (GradeError, ValueError, TypeError):
                record["clv_status"] = "CLV_LINE_OR_PAIR_INVALID"
            rows.append(record)
    return rows
