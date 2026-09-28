#!/usr/bin/env python3
"""Capture one forward-only CFB DraftKings market snapshot when a window is due."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path

from sportsedge.sports.cfb.forward_market_capture import plan_capture, validate_draftkings_snapshot
from sportsedge.sports.cfb.odds_source import fetch_cfb_odds

KEY_NAMES = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)


def _load(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"CFB_SCOREBOARD_OBJECT_REQUIRED:{path}")
    return payload


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--scoreboard", type=Path, action="append", required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--now")
    args = p.parse_args()

    now = args.now or datetime.now(timezone.utc).isoformat()
    plan = plan_capture([_load(path) for path in args.scoreboard], now=now)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "plan.json").write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if not plan["capture_due"]:
        status = {
            "status": "SKIP_OUTSIDE_CFB_FORWARD_MARKET_WINDOWS",
            "promotion_authority": False,
            "paired_market_evidence": False,
        }
        (args.out_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(status, sort_keys=True))
        return 0

    keys = [os.environ.get(name, "") for name in KEY_NAMES]
    result = fetch_cfb_odds(keys)
    raw = result.value.raw
    validation = validate_draftkings_snapshot(result.value.payload)
    captured_at = datetime.now(timezone.utc).isoformat()
    digest = sha256(raw).hexdigest()
    (args.out_dir / "snapshot.json").write_bytes(raw)
    meta = {
        "schema": "SPORTSEDGE_CFB_FORWARD_MARKET_SNAPSHOT_V1",
        "source": "THE_ODDS_API_CURRENT",
        "bookmaker": "draftkings",
        "markets": ["h2h", "spreads", "totals"],
        "captured_at_utc": captured_at,
        "payload_sha256": digest,
        "bytes": len(raw),
        "credential_slot": result.key_slot,
        "prior_key_failure_count": len(result.failures),
        "decision_due_scoreboard_events": plan["decision_due"],
        "close_due_scoreboard_events": plan["close_due"],
        "provider_validation": validation,
        "forward_only": True,
        "retroactive_point_in_time_claim": False,
        "promotion_authority": False,
        "paired_market_evidence": False,
        "model_p_created": False,
        "eligibility_changed": False,
    }
    (args.out_dir / "snapshot.meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if validation.get("snapshot_usable") is not True:
        status = {
            "status": "BLOCKED_PROVIDER_SNAPSHOT_NO_USABLE_DRAFTKINGS_MARKETS",
            "captured_at_utc": captured_at,
            "payload_sha256": digest,
            "event_count": validation["event_count"],
            "draftkings_event_count": validation["draftkings_event_count"],
            "two_sided_market_count": validation["two_sided_market_count"],
            "promotion_authority": False,
            "paired_market_evidence": False,
        }
        (args.out_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(status, sort_keys=True))
        return 78

    status = {
        "status": "CFB_FORWARD_MARKET_SNAPSHOT_CAPTURED",
        "captured_at_utc": captured_at,
        "payload_sha256": digest,
        "event_count": validation["event_count"],
        "draftkings_event_count": validation["draftkings_event_count"],
        "two_sided_market_count": validation["two_sided_market_count"],
        "promotion_authority": False,
        "paired_market_evidence": False,
    }
    (args.out_dir / "status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
