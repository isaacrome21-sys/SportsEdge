"""Append-only line snapshot store for [<SPORT> LINES] issues.

Muse posts one lines issue per game and EDITS it hourly until start, so the
issue body only ever holds the latest board. Every card run on that issue
appends one immutable snapshot line to

    ledger/line_snapshots/<sport>/<issue>.jsonl

Rules (shared by every sport's grader / CLV code):

* Snapshots are never rewritten or deleted. ``append_snapshot`` only opens the
  file in append mode; an exact re-run (same Captured time + same content hash)
  is skipped so reruns stay idempotent.
* ``Captured: <ISO with offset>`` (body line 2) is the snapshot time. Bodies
  without an offset-aware Captured line are refused (no guessed time).
* Entry for a pick = first snapshot (by Captured) whose ``picks`` contain it,
  and only if that snapshot was captured before game start.
* Close = last snapshot with Captured strictly before game start.
* No pre-start snapshot -> fail closed (``None`` / explicit status), never a
  guessed or post-start price.
* Owner ruling (2026-10-25, entry-capture policy): a snapshot counts only if
  its ``recorded_at`` is an offset-aware time, its claimed ``Captured`` is not
  later than ``recorded_at`` (+ ``CLOCK_SKEW``), and it was RECORDED before
  game start (a pregame Captured appended after start is a backfill and is
  ignored). The close must be a distinct snapshot captured strictly after the
  entry; entry == close -> ``NO_DISTINCT_CLOSE`` (never a zero-CLV row).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

SNAPSHOT_ROOT = Path("ledger/line_snapshots")
SCHEMA = "sportsedge.line_snapshot.v1"
SPORTS = {"mlb", "nfl", "cfb", "nba", "nhl"}
CLOCK_SKEW = timedelta(seconds=120)
_CAPTURED = re.compile(r"^\s*captured\s*:?\s*(\S+)\s*$", re.I)


class SnapshotError(ValueError):
    pass


def parse_captured_at(body: str) -> datetime | None:
    """Offset-aware ``Captured:`` time from the first lines of a body, else None."""
    for raw in str(body or "").splitlines()[:6]:
        match = _CAPTURED.match(raw.strip().strip("`"))
        if match:
            try:
                value = datetime.fromisoformat(match.group(1).replace("Z", "+00:00"))
            except ValueError:
                return None
            return value if value.tzinfo else None
    return None


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise SnapshotError(f"naive timestamp refused: {value}")
    return parsed


def snapshot_path(sport: str, issue_number: int, root: Path = SNAPSHOT_ROOT) -> Path:
    sport = sport.lower()
    if sport not in SPORTS:
        raise SnapshotError(f"unknown sport: {sport}")
    return Path(root) / sport / f"{int(issue_number)}.jsonl"


def _content_hash(record: dict[str, Any]) -> str:
    core = {k: record.get(k) for k in ("game", "captured_at", "board", "picks", "body")}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


def build_snapshot(
    *,
    sport: str,
    issue_number: int,
    body: str,
    title: str | None,
    game: dict[str, Any],
    board: list[dict[str, Any]],
    picks: list[dict[str, Any]],
    recorded_at: str,
) -> dict[str, Any]:
    captured = parse_captured_at(body)
    if captured is None:
        raise SnapshotError("NO_CAPTURED_LINE: body has no offset-aware 'Captured:' line")
    try:
        recorded = _parse_dt(recorded_at)
    except ValueError as exc:
        raise SnapshotError(f"RECORDED_AT_INVALID: {recorded_at}") from exc
    if recorded is None:
        raise SnapshotError("RECORDED_AT_INVALID: missing")
    if captured > recorded + CLOCK_SKEW:
        raise SnapshotError(f"CAPTURE_IN_FUTURE: captured {captured.isoformat()} > recorded {recorded_at}")
    for pick in picks:
        if "pick" not in pick or "price" not in pick:
            raise SnapshotError(f"pick needs 'pick' and 'price': {pick}")
    record = {
        "schema": SCHEMA,
        "sport": sport.lower(),
        "issue_number": int(issue_number),
        "title": title,
        "game": game,
        "captured_at": captured.isoformat(),
        "recorded_at": recorded_at,
        "board": board,
        "picks": picks,
        "body": body,
    }
    record["content_sha256"] = _content_hash(record)
    return record


def load_snapshots(sport: str, issue_number: int, root: Path = SNAPSHOT_ROOT) -> list[dict[str, Any]]:
    path = snapshot_path(sport, issue_number, root)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def append_snapshot(record: dict[str, Any], root: Path = SNAPSHOT_ROOT) -> bool:
    """Append one snapshot. Returns False when an identical snapshot already exists."""
    path = snapshot_path(record["sport"], record["issue_number"], root)
    existing = load_snapshots(record["sport"], record["issue_number"], root)
    if any(s.get("content_sha256") == record["content_sha256"] for s in existing):
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:  # append-only, never rewrite
        handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    return True


def _ordered(snapshots: Iterable[dict[str, Any]]) -> list[tuple[datetime, int, dict[str, Any]]]:
    rows = [(_parse_dt(s["captured_at"]), i, s) for i, s in enumerate(snapshots)]
    return sorted(rows, key=lambda r: (r[0], r[1]))


def _trusted_recorded_at(snap: dict[str, Any]) -> datetime | None:
    """Offset-aware recorded_at consistent with the claimed capture, else None."""
    try:
        recorded = _parse_dt(snap.get("recorded_at"))
        captured = _parse_dt(snap.get("captured_at"))
    except (ValueError, TypeError):
        return None
    if recorded is None or captured is None or captured > recorded + CLOCK_SKEW:
        return None
    return recorded


def _start(game_start: datetime | str | None) -> datetime | None:
    try:
        start = _parse_dt(game_start) if isinstance(game_start, str) else game_start
    except (ValueError, TypeError):
        return None
    if start is not None and start.tzinfo is None:
        return None
    return start


def pre_start(snapshots: Iterable[dict[str, Any]], game_start: datetime | str | None) -> list[dict[str, Any]]:
    """Snapshots captured AND recorded strictly before start, oldest first.

    Unknown, naive or malformed start -> []. Snapshots without a trusted
    ``recorded_at`` are ignored (fail closed)."""
    start = _start(game_start)
    if start is None:
        return []
    out = []
    for at, _, snap in _ordered(snapshots):
        recorded = _trusted_recorded_at(snap)
        if at < start and recorded is not None and recorded < start:
            out.append(snap)
    return out


def close_snapshot(snapshots: Iterable[dict[str, Any]], game_start: datetime | str | None) -> dict[str, Any] | None:
    pre = pre_start(snapshots, game_start)
    return pre[-1] if pre else None


def _norm_pick(text: str) -> str:
    return " ".join(str(text).lower().split())


@dataclass(frozen=True)
class EntryClose:
    status: str  # OK | NO_PRESTART_SNAPSHOT | PICK_NOT_IN_PRESTART_SNAPSHOT | NO_DISTINCT_CLOSE
    entry: dict[str, Any] | None = None  # snapshot where pick first appeared
    entry_pick: dict[str, Any] | None = None  # that snapshot's pick record (price)
    close: dict[str, Any] | None = None  # last pre-start snapshot, strictly after entry


def entry_and_close(
    snapshots: Iterable[dict[str, Any]], pick: str, game_start: datetime | str | None
) -> EntryClose:
    """Helper for graders/CLV: entry = first pre-start snapshot listing ``pick``;
    close = last pre-start snapshot. Fails closed with an explicit status."""
    pre = pre_start(snapshots, game_start)
    if not pre:
        return EntryClose("NO_PRESTART_SNAPSHOT")
    want = _norm_pick(pick)
    for snap in pre:
        for rec in snap.get("picks") or []:
            if _norm_pick(rec.get("pick", "")) == want:
                close = pre[-1]
                if _parse_dt(close["captured_at"]) <= _parse_dt(snap["captured_at"]):
                    return EntryClose("NO_DISTINCT_CLOSE", snap, rec, None)
                return EntryClose("OK", snap, rec, close)
    return EntryClose("PICK_NOT_IN_PRESTART_SNAPSHOT", close=pre[-1])
