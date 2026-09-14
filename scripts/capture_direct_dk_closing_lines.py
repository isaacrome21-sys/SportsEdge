#!/usr/bin/env python3
"""Prospective direct-DraftKings game-market archive.

This lane is a zero-authority transport fallback when the paid multi-book archive is
unavailable. It preserves exact provider bytes, records receipt time after HTTP, and
writes only exact two-sided DraftKings ML/spread/total observations inside the frozen
closing-line windows. Rows are NOT_EVIDENCE until a sport-specific admission contract
independently accepts them.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.draftkings_game_market_source import fetch_board, normalize_board

UTC = timezone.utc
POLICY_PATH = ROOT / "config/closing_line_archive_policy_v1.json"
SPORTS = ("americanfootball_nfl", "americanfootball_ncaaf", "baseball_mlb")

class DirectDKArchiveError(RuntimeError):
    pass


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except Exception as exc:
        raise DirectDKArchiveError("DIRECT_DK_TIMESTAMP_INVALID") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise DirectDKArchiveError("DIRECT_DK_TIMESTAMP_INVALID")
    return dt.astimezone(UTC)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _windows(start: datetime, receipt: datetime, policy: Mapping[str, Any]) -> tuple[str, ...]:
    lead = (start - receipt).total_seconds() / 60.0
    if lead <= 0:
        return ()
    return tuple(name for name, bounds in policy["windows"].items()
                 if float(bounds["min_minutes_before_start"]) <= lead <= float(bounds["max_minutes_before_start"]))


def _persist_raw(root: Path, sport: str, raw: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(raw).hexdigest()
    rel = Path("archive/direct-dk/raw") / sport / f"{digest}.json"
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != raw:
        raise DirectDKArchiveError("DIRECT_DK_RAW_HASH_COLLISION")
    if not target.exists():
        target.write_bytes(raw)
    return rel.as_posix(), digest


def _append(root: Path, row: Mapping[str, Any]) -> None:
    date = str(row["commence_time"])[:10]
    target = root / "archive/direct-dk" / str(row["sport_key"]) / f"{date}.ndjson"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(row), sort_keys=True) + "\n")


def capture(*, out_dir: Path, policy: Mapping[str, Any]) -> dict[str, Any]:
    if policy.get("policy_id") != "CLOSING_LINE_ARCHIVE_V1" or policy.get("promotion_authority") is not False:
        raise DirectDKArchiveError("DIRECT_DK_PARENT_POLICY_INVALID")
    report: dict[str, Any] = {
        "contract": "SPORTSEDGE_DIRECT_DK_CLOSING_ARCHIVE_V1",
        "evidence_class": "NOT_EVIDENCE",
        "promotion_authority": False,
        "evidence_clock_authority": False,
        "sports": {},
    }
    total = 0
    for sport in SPORTS:
        board = fetch_board(sport)
        receipt = board.received_at
        raw_path, raw_sha = _persist_raw(out_dir, sport, board.raw)
        normalized = normalize_board(board)
        rows = []
        for item in normalized:
            start = _parse_ts(item["commence_time"])
            windows = _windows(start, receipt, policy)
            for window in windows:
                material = "\n".join((sport, str(item["provider_event_id"]), str(item["market"]),
                                        str(item["outcome"]), str(item.get("point")), window,
                                        _iso(receipt), raw_sha))
                row = {
                    **item,
                    "schema_version": "DIRECT_DK_CLOSING_ROW_V1",
                    "policy_id": policy["policy_id"],
                    "evidence_class": "NOT_EVIDENCE",
                    "promotion_authority": False,
                    "evidence_clock_authority": False,
                    "window": window,
                    "captured_at": _iso(receipt),
                    "timestamp_semantics": "HTTP_RESPONSE_RECEIPT_UPPER_BOUND",
                    "raw_relative_path": raw_path,
                    "raw_sha256": raw_sha,
                    "observation_id": hashlib.sha256(material.encode()).hexdigest(),
                    "paired_two_sided": True,
                    "historical_backfill": False,
                }
                _append(out_dir, row)
                rows.append(row)
        report["sports"][sport] = {
            "source_uri": board.source_uri,
            "received_at": _iso(receipt),
            "raw_relative_path": raw_path,
            "raw_sha256": raw_sha,
            "normalized_rows_seen": len(normalized),
            "rows_written": len(rows),
        }
        total += len(rows)
    report["total_rows_written"] = total
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=str(POLICY_PATH))
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--status-out", default=None)
    args = parser.parse_args(argv)
    try:
        policy = json.loads(Path(args.policy).read_text())
        report = capture(out_dir=Path(args.out_dir), policy=policy)
    except Exception as exc:
        report = {"state": "BLOCKED", "reason": f"{type(exc).__name__}:{exc}"}
        text = json.dumps(report, indent=2, sort_keys=True)
        if args.status_out:
            Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.status_out).write_text(text + "\n")
        print(text, file=sys.stderr)
        return 2
    text = json.dumps(report, indent=2, sort_keys=True)
    if args.status_out:
        Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.status_out).write_text(text + "\n")
    print(text)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
