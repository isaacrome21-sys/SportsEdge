#!/usr/bin/env python3
"""Deterministic MLB PIT replay scorer bound to MLB_REPLAY_POLICY_V1.

Implementation pattern informed by public chronological walk-forward projects, but
all evidence must be generated from SportsEdge inputs. This script never imports
third-party predictions/results and grants no promotion/OFFICIAL authority.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

POLICY_ID = "MLB_REPLAY_POLICY_V1"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def score(rows: list[dict[str, str]]) -> dict[str, Any]:
    required = {"decision_id", "slate_date_ct", "market", "model_p", "outcome", "decision_no_vig_p", "close_no_vig_p", "net_return", "risked_stake"}
    if not rows:
        return {"n": 0, "status": "NO_EVIDENCE"}
    missing = required - set(rows[0])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    ids = [r["decision_id"] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate decision_id forbidden")

    ps = [f(r, "model_p") for r in rows]
    ys = [f(r, "outcome") for r in rows]
    if any(not 0.0 <= p <= 1.0 for p in ps) or any(y not in (0.0, 1.0) for y in ys):
        raise ValueError("invalid probability/outcome")
    eps = 1e-15
    brier = mean([(p-y)**2 for p, y in zip(ps, ys)])
    logloss = mean([-(y*math.log(max(eps,p)) + (1-y)*math.log(max(eps,1-p))) for p,y in zip(ps,ys)])
    clv = [f(r,"close_no_vig_p") - f(r,"decision_no_vig_p") for r in rows]
    risk = sum(f(r,"risked_stake") for r in rows)
    roi = sum(f(r,"net_return") for r in rows) / risk if risk > 0 else None

    clusters: dict[str, list[float]] = defaultdict(list)
    for r, x in zip(rows, clv):
        clusters[r["slate_date_ct"]].append(x)
    cluster_means = [sum(v)/len(v) for v in clusters.values()]
    return {
        "status": "SCORED_NOT_PROMOTED",
        "n": len(rows),
        "slate_clusters": len(clusters),
        "brier": brier,
        "log_loss": logloss,
        "mean_clv": mean(clv),
        "roi": roi,
        "cluster_mean_clv": mean(cluster_means),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--policy", type=Path, default=Path("config/mlb_replay_policy_v1.json"))
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("policy_id") != POLICY_ID or policy.get("status") != "FROZEN_PRE_REPLAY":
        raise SystemExit("frozen MLB replay policy identity/status mismatch")
    rows = load_rows(args.input)
    by_market: dict[str, list[dict[str,str]]] = defaultdict(list)
    for row in rows:
        by_market[row["market"]].append(row)
    report = {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "policy_sha256": sha256_file(args.policy),
        "input_sha256": sha256_file(args.input),
        "markets": {m: score(rs) for m,rs in sorted(by_market.items())},
        "governance": {
            "third_party_predictions_imported": False,
            "historical_backfill_promoted": False,
            "model_p_created": False,
            "floor_derived": False,
            "eligibility_changed": False,
            "truth_gate_pass_granted": False,
            "official_status_granted": False,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"status":"OK","markets":len(report["markets"]),"out":str(args.out)}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
