#!/usr/bin/env python3
"""Exercise the real reservation lifecycle with a local non-network placement stub."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from sportsedge.shadow_execution import ShadowExecutionError, execute_shadow


def _shadow_stub(row: Mapping[str, Any]) -> Mapping[str, Any]:
    """Pure local placement simulator. It never contacts a sportsbook."""
    book = str(row.get("book_key") or "").strip()
    game_id = str(row.get("game_id") or "").strip()
    market = str(row.get("market") or "").strip()
    side = str(row.get("side") or "").strip()
    wager_key = str(row.get("wager_key") or "").strip()
    odds = row.get("american_odds")
    model_p = row.get("model_p")
    if not (book and game_id and market and side and wager_key):
        return {"accepted": False, "reason": "SHADOW_IDENTITY_INCOMPLETE"}
    try:
        price = float(odds)
        probability = float(model_p)
    except (TypeError, ValueError):
        return {"accepted": False, "reason": "SHADOW_PRICE_OR_MODEL_P_INVALID"}
    if not isfinite(price) or not isfinite(probability) or not (0.0 < probability < 1.0):
        return {"accepted": False, "reason": "SHADOW_PRICE_OR_MODEL_P_INVALID"}
    return {"accepted": True, "reason": "SHADOW_LOCAL_SIMULATOR_ACCEPT"}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--ledger", default="artifacts/live_mlb_decision_ledger.json")
    p.add_argument("--reservation-root", default=".cache/sportsedge/execution-reservations")
    p.add_argument("--output", default="artifacts/shadow_execution.json")
    args = p.parse_args()

    ledger_path = Path(args.ledger)
    if not ledger_path.exists():
        raise SystemExit("decision ledger missing")
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    decisions = ledger.get("decisions") or []
    if not isinstance(decisions, list):
        raise SystemExit("decision ledger decisions malformed")

    attempted = []
    failures = []
    for row in decisions:
        if not isinstance(row, Mapping) or row.get("execution_ready") is not True:
            continue
        try:
            attempted.append(
                execute_shadow(
                    row,
                    args.reservation_root,
                    placement_stub=_shadow_stub,
                )
            )
        except ShadowExecutionError as exc:
            failures.append({
                "decision_id": row.get("decision_id"),
                "wager_key": row.get("wager_key"),
                "reason": str(exc),
            })

    now = datetime.now(timezone.utc)
    payload = {
        "schema_version": "sportsedge_shadow_execution_v1",
        "generated_at_utc": now.isoformat(),
        "ledger_run_id": ledger.get("run_id"),
        "execution_mode": "SHADOW",
        "real_sportsbook_calls": 0,
        "eligible_decision_count": sum(1 for x in decisions if isinstance(x, Mapping) and x.get("execution_ready") is True),
        "attempted_count": len(attempted),
        "failure_count": len(failures),
        "attempts": attempted,
        "failures": failures,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
