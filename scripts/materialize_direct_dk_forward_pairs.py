#!/usr/bin/env python3
"""Materialize prospective direct-DraftKings pairs from the immutable archive.

This is an acquisition/provenance bridge only. It does not rewrite confirmation
captures, create Model_P, grant Truth Gate/promotion authority, or backfill.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.validation.direct_dk_forward_pairing import _load_policy, load_ndjson, pair_rows


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--archive-root", type=Path, required=True)
    p.add_argument("--policy", type=Path, default=Path("config/direct_dk_forward_pair_admission_v1.json"))
    p.add_argument("--sport", default="americanfootball_nfl")
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    policy = _load_policy(args.policy)
    paths = sorted(args.archive_root.rglob("*.ndjson"))
    rows = load_ndjson(paths)
    report = pair_rows(rows, policy, args.sport)
    report["source_archive_root"] = str(args.archive_root)
    report["source_file_count"] = len(paths)
    report["historical_backfill"] = False
    report["confirmation_capture_rewritten"] = False
    report["evidence_clock_authority"] = False
    report["may_create_model_p"] = False
    report["truth_gate_pass_granted"] = False
    report["promotion_authority"] = False
    report["official_status_granted"] = False

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "pair_count": report["pair_count"], "out": str(args.out)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
