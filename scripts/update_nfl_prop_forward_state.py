#!/usr/bin/env python3
"""Durably apply one prospective NFL prop snapshot to forward evidence state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.prop_forward_capture import apply_snapshot


def _json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NFL_PROP_FORWARD_JSON_INVALID:{path}") from exc


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"NFL_PROP_FORWARD_JSONL_INVALID:{path}:{i}") from exc
        if not isinstance(row, dict):
            raise SystemExit(f"NFL_PROP_FORWARD_JSONL_ROW_INVALID:{path}:{i}")
        rows.append(row)
    return rows


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    payload = _json(args.snapshot)
    if not isinstance(payload, dict):
        raise SystemExit("NFL_PROP_FORWARD_SNAPSHOT_NOT_OBJECT")
    if payload.get("contract") != "NFL_PROP_FORWARD_RAW_SNAPSHOT_V1":
        raise SystemExit("NFL_PROP_FORWARD_SNAPSHOT_CONTRACT_INVALID")
    if payload.get("reconstructed") is not False or payload.get("backfilled") is not False:
        raise SystemExit("NFL_PROP_FORWARD_SNAPSHOT_RECONSTRUCTION_FORBIDDEN")
    quotes = payload.get("quotes")
    starts = payload.get("event_starts")
    if not isinstance(quotes, list):
        raise SystemExit("NFL_PROP_FORWARD_QUOTES_NOT_LIST")
    if not isinstance(starts, dict):
        raise SystemExit("NFL_PROP_FORWARD_EVENT_STARTS_NOT_OBJECT")

    decisions_path = args.state_dir / "decisions.jsonl"
    closes_path = args.state_dir / "closes.jsonl"
    blocked_path = args.state_dir / "missed_or_blocked.jsonl"
    prior_decisions = _jsonl(decisions_path)
    prior_closes = _jsonl(closes_path)

    result = apply_snapshot(
        quotes,
        captured_at=payload.get("captured_at"),
        event_starts=starts,
        existing_decisions=prior_decisions,
        existing_closes=prior_closes,
    )
    new_decisions = [dict(x) for x in result.decisions]
    new_closes = [dict(x) for x in result.closes]
    blocked = [dict(x) for x in result.missed_or_blocked]
    for row in (*new_decisions, *new_closes):
        row["source_snapshot_sha256"] = str(payload.get("snapshot_sha256") or "")
        row["code_git_sha"] = str(payload.get("code_git_sha") or "").lower()
    for row in blocked:
        row["captured_at"] = str(payload.get("captured_at") or "")
        row["source_snapshot_sha256"] = str(payload.get("snapshot_sha256") or "")
        row["code_git_sha"] = str(payload.get("code_git_sha") or "").lower()

    _append_jsonl(decisions_path, new_decisions)
    _append_jsonl(closes_path, new_closes)
    _append_jsonl(blocked_path, blocked)

    summary = {
        "contract": "NFL_PROP_FORWARD_STATE_UPDATE_V1",
        "new_decisions": len(new_decisions),
        "new_closes": len(new_closes),
        "new_missed_or_blocked": len(blocked),
        "decision_total": len(prior_decisions) + len(new_decisions),
        "close_total": len(prior_closes) + len(new_closes),
        "promotion_authority": False,
        "model_p_created": False,
        "reconstructed": False,
        "backfilled": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
