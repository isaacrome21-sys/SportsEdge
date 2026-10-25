#!/usr/bin/env python3
"""Strict NFL PAPER settlement from stored pregame snapshots and ESPN finals.

Research-only: no quote acquisition, no sportsbook authentication, no promotion.
The game/identity/time and distinct entry/close must be evidenced; missing
player-stat receipts and unsupported period markets stay explicitly blocked.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from sportsedge.line_snapshots import (
    _content_hash, entry_and_close, load_snapshots,
)
from sportsedge.nfl_team_aliases import NflTeamAliasError, resolve_team
from sportsedge.pipeline.grading import FinalResult, GradeError, grade, no_vig_clv, units
from sportsedge.pipeline.picks import PickRecord, PickRecordError

SCHEMA = "NFL_STRICT_PAPER_GRADE_V1"
FINAL_SCHEMA = "NFL_FINAL_SCORES_V1"
SUPPORTED = {"moneyline", "spread", "total"}


class NFLPaperGradeError(ValueError):
    pass


def _time(value: Any) -> datetime:
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise NFLPaperGradeError("NFL_GRADE_TIME_UNVERIFIED") from exc
    if value.tzinfo is None or value.utcoffset() is None:
        raise NFLPaperGradeError("NFL_GRADE_TIME_UNVERIFIED")
    return value


def _team(value: Any) -> str:
    try:
        return resolve_team(str(value or ""))
    except NflTeamAliasError as exc:
        raise NFLPaperGradeError("NFL_GRADE_TEAM_IDENTITY_UNVERIFIED") from exc


def _identity(snapshot: dict[str, Any]) -> tuple[str, str, str]:
    game = snapshot.get("game")
    if not isinstance(game, dict):
        raise NFLPaperGradeError("NFL_GRADE_GAME_IDENTITY_MISSING")
    event_id = str(game.get("game_id") or game.get("event_id") or "").strip()
    if not event_id or not event_id.isdigit():
        raise NFLPaperGradeError("NFL_GRADE_EVENT_ID_MISSING")
    away = _team(game.get("away") or game.get("away_team"))
    home = _team(game.get("home") or game.get("home_team"))
    if away == home:
        raise NFLPaperGradeError("NFL_GRADE_TEAM_IDENTITY_UNVERIFIED")
    return event_id, away, home


def _final(finals: dict[str, Any], identity: tuple[str, str, str]) -> tuple[FinalResult, str]:
    if (not isinstance(finals, dict) or finals.get("schema") != FINAL_SCHEMA
            or finals.get("source") != "ESPN_SCOREBOARD"):
        raise NFLPaperGradeError("NFL_GRADE_FINAL_SOURCE_INVALID")
    event_id, away, home = identity
    matches = [g for g in finals.get("games", []) if str(g.get("game_id")) == event_id]
    if len(matches) != 1:
        raise NFLPaperGradeError("NFL_GRADE_FINAL_EVENT_MISSING_OR_DUPLICATE")
    game = matches[0]
    if (_team(game.get("away_team")) != away
            or _team(game.get("home_team")) != home):
        raise NFLPaperGradeError("NFL_GRADE_FINAL_TEAM_MISMATCH")
    if not str(game.get("status") or "").startswith("STATUS_FINAL"):
        raise NFLPaperGradeError("NFL_GRADE_NOT_FINAL")
    scores = (game.get("away_points"), game.get("home_points"))
    if (any(type(x) is not int or x < 0 for x in scores)
            or not game.get("start_ts")):
        raise NFLPaperGradeError("NFL_GRADE_FINAL_SCORE_OR_START_INVALID")
    start = _time(game["start_ts"])
    return FinalResult(away_score=scores[0], home_score=scores[1]), start.isoformat()


def _canonical_pick(rec: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(rec.get("market") or "").lower(),
        str(rec.get("subject") or "").strip(),
        str(rec.get("selection") or "").upper(),
        str(rec.get("line")),
    )


def _quote(rec: dict[str, Any], snap: dict[str, Any], *, label: str) -> PickRecord:
    if (type(rec.get("price")) is not int or type(rec.get("dk_price")) is not int
            or type(rec.get("opposite_price")) is not int):
        raise NFLPaperGradeError(f"NFL_GRADE_{label}_PAIR_INCOMPLETE")
    if rec["price"] != rec["dk_price"]:
        raise NFLPaperGradeError(f"NFL_GRADE_{label}_PRICE_MISMATCH")
    try:
        pick = PickRecord.from_dict(rec)
    except (PickRecordError, TypeError, ValueError, KeyError) as exc:
        raise NFLPaperGradeError(f"NFL_GRADE_{label}_PICK_INVALID") from exc
    if pick.sport != "NFL" or _time(pick.captured_at) != _time(snap["captured_at"]):
        raise NFLPaperGradeError(f"NFL_GRADE_{label}_IDENTITY_TIME_MISMATCH")
    return pick


def _blocked(issue: int, identity: tuple[str, str, str], key: str, reason: str) -> dict[str, Any]:
    return {"schema": SCHEMA, "issue_number": issue, "game_id": identity[0],
            "pick": key, "status": "BLOCKED", "reason": reason,
            "result": None, "profit_units": None, "clv_no_vig": None,
            "clv_status": reason, "ladder_status": "PAPER", "verified": False}


def grade_issue(issue_number: int, snapshots: list[dict[str, Any]],
                finals: dict[str, Any]) -> list[dict[str, Any]]:
    """Grade only evidenced full-game NFL selections; never infer missing data."""
    if not snapshots:
        raise NFLPaperGradeError("NFL_GRADE_SNAPSHOTS_MISSING")
    identity = _identity(snapshots[0])
    keys: dict[str, tuple[str, str, str, str]] = {}
    for s in snapshots:
        if (s.get("sport") != "nfl" or s.get("issue_number") != issue_number
                or s.get("content_sha256") != _content_hash(s)
                or _identity(s) != identity):
            raise NFLPaperGradeError("NFL_GRADE_SNAPSHOT_IDENTITY_OR_HASH_INVALID")
        for rec in s.get("picks") or []:
            key = str(rec.get("pick") or "").strip()
            if not key:
                raise NFLPaperGradeError("NFL_GRADE_PICK_KEY_MISSING")
            canonical = _canonical_pick(rec)
            if key in keys and keys[key] != canonical:
                raise NFLPaperGradeError("NFL_GRADE_AMBIGUOUS_PICK_KEY")
            keys[key] = canonical
    if not keys:
        raise NFLPaperGradeError("NFL_GRADE_NO_PAPER_PICKS")
    result, game_start = _final(finals, identity)
    out: list[dict[str, Any]] = []
    for key in sorted(keys):
        pair = entry_and_close(snapshots, key, game_start)
        if pair.entry is None or pair.entry_pick is None:
            out.append(_blocked(issue_number, identity, key, pair.status))
            continue
        try:
            entry = _quote(pair.entry_pick, pair.entry, label="ENTRY")
        except NFLPaperGradeError as exc:
            out.append(_blocked(issue_number, identity, key, str(exc)))
            continue
        if entry.market.lower() not in SUPPORTED:
            out.append(_blocked(issue_number, identity, key, "NFL_GRADE_NO_STAT_OR_PERIOD_RECEIPT"))
            continue
        if entry.game:
            parts = entry.game.split("@")
            if len(parts) != 2 or (_team(parts[0]) != identity[1]
                                  or _team(parts[1]) != identity[2]):
                out.append(_blocked(issue_number, identity, key, "NFL_GRADE_CARD_GAME_MISMATCH"))
                continue
        try:
            outcome = grade(entry, result, family=entry.market.lower())
            profit = units(outcome, entry.dk_price)
        except (GradeError, ValueError) as exc:
            out.append(_blocked(issue_number, identity, key, f"NFL_GRADE_RULE_BLOCKED:{exc}"))
            continue
        clv_status, clv = pair.status, None
        if pair.status == "OK" and pair.close is not None:
            matching = [r for r in pair.close.get("picks") or []
                        if str(r.get("pick") or "").strip().lower() == key.lower()]
            if len(matching) != 1:
                clv_status = "NFL_GRADE_NO_CLOSE_PICK_PAIR"
            else:
                try:
                    closing = _quote(matching[0], pair.close, label="CLOSE")
                    if (_canonical_pick(matching[0]) != _canonical_pick(pair.entry_pick)
                            or closing.game != entry.game):
                        raise NFLPaperGradeError("NFL_GRADE_CLOSE_MARKET_IDENTITY_MISMATCH")
                    clv = no_vig_clv(
                        entry.dk_price, entry.opposite_price,
                        closing.dk_price, closing.opposite_price,
                        entry_line=entry.line, close_line=closing.line,
                    )
                    clv_status = "CLV_PAPER_PAIRED"
                except (NFLPaperGradeError, GradeError) as exc:
                    clv_status = str(exc)
        out.append({
            "schema": SCHEMA, "issue_number": issue_number, "game_id": identity[0],
            "pick": key, "market": entry.market, "selection": entry.selection,
            "subject": entry.subject, "line": entry.line,
            "entry_price": entry.dk_price, "entry_opposite": entry.opposite_price,
            "entry_captured_at": pair.entry["captured_at"],
            "status": "PAPER_GRADED", "reason": None,
            "result": outcome, "profit_units": profit,
            "clv_status": clv_status, "clv_no_vig": clv,
            "ladder_status": "PAPER", "verified": False,
        })
    return out


def append_ledger(path: Path, rows: list[dict[str, Any]]) -> int:
    """Append-only idempotence, with conflict refusal; never rewrite a grade."""
    existing: dict[tuple[Any, ...], str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                old = json.loads(line)
                key = (old.get("issue_number"), old.get("game_id"), old.get("pick"))
                digest = hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()
                if key in existing and existing[key] != digest:
                    raise NFLPaperGradeError("NFL_GRADE_EXISTING_LEDGER_CONFLICT")
                existing[key] = digest
    added: list[dict[str, Any]] = []
    for row in rows:
        key = (row["issue_number"], row["game_id"], row["pick"])
        digest = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        if key in existing:
            if existing[key] != digest:
                raise NFLPaperGradeError("NFL_GRADE_LEDGER_IMMUTABLE_CONFLICT")
            continue
        existing[key] = digest
        added.append(row)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for row in added:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
    return len(added)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--issue", type=int, required=True)
    ap.add_argument("--finals-json", type=Path, required=True)
    ap.add_argument("--snapshot-root", type=Path, default=Path("ledger/line_snapshots"))
    ap.add_argument("--ledger", type=Path, required=True)
    args = ap.parse_args(argv)
    try:
        snapshots = load_snapshots("nfl", args.issue, args.snapshot_root)
        finals = json.loads(args.finals_json.read_text(encoding="utf-8"))
        rows = grade_issue(args.issue, snapshots, finals)
        added = append_ledger(args.ledger, rows)
    except (NFLPaperGradeError, OSError, KeyError, TypeError, ValueError) as exc:
        ap.exit(2, f"NFL_PAPER_GRADE_BLOCKED:{type(exc).__name__}:{exc}\n")
    print(json.dumps({"schema": SCHEMA, "status": "PAPER_ONLY",
                      "graded": sum(r["status"] == "PAPER_GRADED" for r in rows),
                      "blocked": sum(r["status"] == "BLOCKED" for r in rows),
                      "added": added}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
