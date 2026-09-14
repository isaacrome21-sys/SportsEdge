#!/usr/bin/env python3
"""Settle stale-price candidate CLV without mislabeling CLV as lane edge.

The underlying exact-contract Pinnacle-close calculation remains unchanged.
This wrapper makes the policy semantics explicit: CLV is a detector/process
check for a stale-price lane. The lane's primary validation metric is realized
ROI on filled wagers; when no real fills exist, persisted-price flat-1u ROI is
the primary research-only proxy. Offered-price ROI is optimistic diagnostic only.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from scripts.analyze_market_maker_radar import _iso, _parse_ts, load_policy
from scripts.settle_market_maker_candidate_ledger import (
    _load_candidates,
    _load_radar_rows,
    _persist_settlement,
    settle_candidate,
    summarize,
)

UTC = timezone.utc
DEFAULT_POLICY = "config/market_maker_radar_v2.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", default=DEFAULT_POLICY)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--ledger-root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--now", default=None)
    args = parser.parse_args(argv)

    policy = load_policy(args.policy)
    now = _parse_ts(args.now) if args.now else datetime.now(UTC)
    archive_root = Path(args.archive_root)
    ledger_root = Path(args.ledger_root)
    candidates = _load_candidates(ledger_root)
    rows = _load_radar_rows(archive_root)

    new = 0
    existing = 0
    pending = 0
    for candidate in candidates:
        settlement = settle_candidate(candidate, rows, policy, now=now)
        if settlement is None:
            pending += 1
            continue
        if _persist_settlement(ledger_root, settlement):
            new += 1
        else:
            existing += 1

    grading = policy["grading"]
    report = {
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "ran_at": _iso(now),
        "candidate_count": len(candidates),
        "new_settlement_count": new,
        "existing_settlement_count": existing,
        "pending_candidate_count": pending,
        "source_family_summary": summarize(ledger_root, policy),
        "primary_metric": grading["primary_metric"],
        "research_only_primary_metric_when_no_fills": grading["research_only_primary_metric_when_no_fills"],
        "process_metric": grading["process_metric"],
        "clv_role": grading["clv_role"],
        "offered_price_roi_role": grading["offered_price_roi_role"],
        "evaluation_checkpoints": grading["evaluation_checkpoints"],
        "result_roi_status": "PENDING_RESULT_AND_EXECUTION_SETTLEMENT",
        "clv_settlement_status": "PROCESS_CHECK_ONLY",
        "model_p_authority": False,
        "promotion_authority": False,
        "staking_authority": False,
        "official_authority": False,
        "automatic_wager_authority": False,
    }
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
