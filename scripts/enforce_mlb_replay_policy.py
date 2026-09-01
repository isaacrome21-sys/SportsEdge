#!/usr/bin/env python3
"""Bind derived MLB validation state to the exact frozen replay policy."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.mlb.replay_policy import (  # noqa: E402
    MLBReplayPolicyError,
    enforce_replay_policy_binding,
    load_replay_policy,
)

REQUIRED_GATES = (
    "historical_point_in_time",
    "untouched_holdout",
    "calibration",
    "settlement_semantics",
    "forward_evidence",
    "production_parity",
)


def _as_of(value: str | None) -> date:
    if value in (None, ""):
        return datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise SystemExit("MLB_REPLAY_AUDIT_AS_OF_DATE_INVALID") from exc


def _summary(markets: dict) -> dict[str, int]:
    rows = list(markets.values())
    return {
        "markets": len(rows),
        "gate_passes": sum(v.get("status") == "PASS" for row in rows for v in row.values() if isinstance(v, dict)),
        "gate_failures": sum(v.get("status") == "FAIL" for row in rows for v in row.values() if isinstance(v, dict)),
        "gate_pending": sum(v.get("status") == "PENDING" for row in rows for v in row.values() if isinstance(v, dict)),
        "fully_validated_markets": sum(
            all(isinstance(row.get(g), dict) and row[g].get("status") == "PASS" for g in REQUIRED_GATES)
            for row in rows
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="config/mlb_replay_policy_v1.json")
    ap.add_argument("--input", default="artifacts/mlb-validation/derived_status.json")
    ap.add_argument("--output")
    ap.add_argument("--as-of-date")
    args = ap.parse_args()

    source = Path(args.input)
    target = Path(args.output) if args.output else source
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("MLB_REPLAY_DERIVED_STATUS_UNREADABLE") from exc
    if tuple(payload.get("required_gates") or ()) != REQUIRED_GATES:
        raise SystemExit("MLB_REPLAY_DERIVED_GATE_CONTRACT_MISMATCH")
    markets = payload.get("markets")
    if not isinstance(markets, dict) or not markets:
        raise SystemExit("MLB_REPLAY_DERIVED_MARKETS_REQUIRED")

    try:
        identity = load_replay_policy(Path(args.policy))
        governed = enforce_replay_policy_binding(
            markets,
            policy_identity=identity,
            as_of_date=_as_of(args.as_of_date),
        )
    except MLBReplayPolicyError as exc:
        raise SystemExit(str(exc)) from exc

    payload["markets"] = governed
    payload["summary"] = _summary(governed)
    payload["replay_policy"] = {
        **identity,
        "enforced": True,
        "as_of_date": _as_of(args.as_of_date).isoformat(),
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"replay_policy": payload["replay_policy"], "summary": payload["summary"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
