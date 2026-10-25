#!/usr/bin/env python3
"""Research NFL score grading from immutable entry and distinct close receipts.

No caller-supplied prices or issue timestamps are accepted. Only full-game
moneyline/spread/total picks with canonical fields can be settled here; props
need independently captured final statistics and remain unsupported.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from scripts.capture_nfl_final_scores import SCHEMA
from sportsedge.line_snapshots import entry_and_close, load_snapshots
from sportsedge.pipeline.grading import FinalResult, grade, no_vig_clv, units
from sportsedge.pipeline.intake import parse_envelope, parse_issue
from sportsedge.nfl_team_aliases import resolve_team


def _team(value):
    return resolve_team(value)


def _pair(snapshot, pick, final):
    # Parse the preserved original board; never substitute a caller's close.
    parse_envelope(snapshot["body"], "NFL", title=snapshot.get("title"))
    games = parse_issue(snapshot["body"], "NFL", title=snapshot.get("title")).games
    if len(games) != 1:
        raise ValueError("NFL_GRADE_AMBIGUOUS_GAME")
    game = games[0]
    if (_team(game.away), _team(game.home)) != (_team(final["away_team"]), _team(final["home_team"])):
        raise ValueError("NFL_GRADE_GAME_MISMATCH")
    found = []
    for market in game.markets:
        if market.market != pick["market"] or market.subject is not None:
            continue
        if pick["selection"] not in (market.side_a, market.side_b):
            continue
        first = pick["selection"] == market.side_a
        line = -market.line if market.family == "spread" and not first else market.line
        if line != pick.get("line"):
            continue
        found.append((market.price_a, market.price_b) if first else (market.price_b, market.price_a))
    if len(found) != 1:
        raise ValueError("NFL_GRADE_PAIRED_MARKET_MISSING_OR_AMBIGUOUS")
    return found[0]


def grade_snapshot_pick(snapshots, pick_name, final):
    row = {"pick": pick_name, "status": "BLOCKED", "outcome": None,
           "units": None, "clv": None, "ladder_status": "PAPER"}
    try:
        if not str(final.get("status", "")).startswith("STATUS_FINAL"):
            raise ValueError("NFL_GRADE_NOT_FINAL")
        scores = [final["away_points"], final["home_points"]]
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or
               not math.isfinite(x) or x < 0 or int(x) != x for x in scores):
            raise ValueError("NFL_GRADE_INVALID_SCORE")
        result = entry_and_close(snapshots, pick_name, final.get("start_ts"))
        if result.status != "OK":
            raise ValueError(result.status)
        entry, close, pick = result.entry, result.close, result.entry_pick
        if any(s.get("sport") != "nfl" for s in (entry, close)):
            raise ValueError("NFL_GRADE_SPORT_MISMATCH")
        if entry.get("issue_number") != close.get("issue_number"):
            raise ValueError("NFL_GRADE_ISSUE_MISMATCH")
        if pick.get("market") not in {"moneyline", "spread", "total"}:
            raise ValueError("NFL_GRADE_UNSUPPORTED_MARKET")
        expected = {"OVER", "UNDER"} if pick["market"] == "total" else {"AWAY", "HOME"}
        if pick.get("selection") not in expected:
            raise ValueError("NFL_GRADE_SELECTION_INVALID")
        if pick["market"] != "moneyline":
            line = pick.get("line")
            if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
                raise ValueError("NFL_GRADE_LINE_INVALID")
        ep, eo = _pair(entry, pick, final)
        cp, co = _pair(close, pick, final)
        if isinstance(pick.get("price"), bool) or pick.get("price") != ep:
            raise ValueError("NFL_GRADE_ENTRY_PRICE_MISMATCH")
        outcome = grade(pick, FinalResult(*scores), family=pick["market"])
        clv = no_vig_clv(ep, eo, cp, co, entry_line=pick.get("line"), close_line=pick.get("line"))
        row.update(status="GRADED_PAPER", outcome=outcome, units=units(outcome, ep), clv=clv,
                   market=pick["market"], game_id=str(final["game_id"]),
                   entry_captured_at=entry["captured_at"], close_captured_at=close["captured_at"],
                   entry_sha256=entry.get("content_sha256"), close_sha256=close.get("content_sha256"))
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        row["reason"] = str(exc)
    return row


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue", required=True, type=int)
    ap.add_argument("--game-id", required=True)
    ap.add_argument("--finals", required=True, type=Path)
    ap.add_argument("--snapshot-root", type=Path, default=Path("ledger/line_snapshots"))
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args(argv)
    doc = json.loads(args.finals.read_text())
    if doc.get("schema") != SCHEMA:
        raise ValueError("NFL_FINALS_SCHEMA_INVALID")
    finals = [g for g in doc.get("games", []) if str(g["game_id"]) == args.game_id]
    if len(finals) != 1:
        raise ValueError("NFL_GRADE_FINAL_MISSING_OR_AMBIGUOUS")
    snapshots = load_snapshots("nfl", args.issue, args.snapshot_root)
    names = sorted({p["pick"] for s in snapshots for p in s.get("picks", []) if p.get("pick")})
    rows = [grade_snapshot_pick(snapshots, name, finals[0]) for name in names]
    output = {"schema": "NFL_SNAPSHOT_GRADES_V1", "issue": args.issue,
              "status": "PAPER" if rows else "NO_CAPTURED_PICKS", "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(output, indent=2, allow_nan=False) + "\n"
    if args.output.exists() and args.output.read_text() != content:
        raise ValueError("NFL_GRADE_OUTPUT_CONFLICT")
    args.output.write_text(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
