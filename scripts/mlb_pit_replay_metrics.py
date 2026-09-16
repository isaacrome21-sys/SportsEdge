#!/usr/bin/env python3
"""Deterministic MLB PIT replay scorer bound to MLB_REPLAY_POLICY_V1.

Implementation pattern informed by public chronological walk-forward projects, but
all evidence must be generated from SportsEdge inputs. This script never imports
third-party predictions/results and grants no Model_P, Truth Gate, promotion,
staking, eligibility, or OFFICIAL authority.
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
# Git blob identity of the already-frozen config/mlb_replay_policy_v1.json bytes.
FROZEN_POLICY_GIT_BLOB_SHA = "5f00bd1b2f7cbe5c86070eb7bfa9a847e553d953"

REQUIRED = {
    "decision_id", "game_id", "slate_date_ct", "market", "side", "book",
    "model_p", "outcome", "decision_no_vig_p", "close_no_vig_p",
    "net_return", "risked_stake",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_blob_sha(path: Path) -> str:
    data = path.read_bytes()
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def f(row: dict[str, str], key: str) -> float:
    x = float(row[key])
    if not math.isfinite(x):
        raise ValueError(f"non-finite numeric value: {key}")
    return x


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def validate_rows(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    missing = REQUIRED - set(rows[0])
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")

    decision_ids: set[str] = set()
    observations: set[tuple[str, str, str, str]] = set()
    for row in rows:
        if any(not row.get(k, "").strip() for k in ("decision_id", "game_id", "slate_date_ct", "market", "side", "book")):
            raise ValueError("blank decision identity field forbidden")
        decision_id = row["decision_id"]
        if decision_id in decision_ids:
            raise ValueError("duplicate decision_id forbidden")
        decision_ids.add(decision_id)

        observation = (row["game_id"], row["market"], row["side"], row["book"])
        if observation in observations:
            raise ValueError("duplicate game/market/side/book observation forbidden")
        observations.add(observation)

        p = f(row, "model_p")
        y = f(row, "outcome")
        decision_p = f(row, "decision_no_vig_p")
        close_p = f(row, "close_no_vig_p")
        risk = f(row, "risked_stake")
        if not 0.0 <= p <= 1.0 or y not in (0.0, 1.0):
            raise ValueError("invalid probability/outcome")
        if not 0.0 <= decision_p <= 1.0 or not 0.0 <= close_p <= 1.0:
            raise ValueError("invalid no-vig probability")
        if risk < 0.0:
            raise ValueError("negative risked_stake forbidden")
        f(row, "net_return")


def score(rows: list[dict[str, str]], *, validated: bool = False) -> dict[str, Any]:
    if not rows:
        return {"n": 0, "status": "NO_EVIDENCE"}
    if not validated:
        validate_rows(rows)

    ps = [f(r, "model_p") for r in rows]
    ys = [f(r, "outcome") for r in rows]
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
    ap.add_argument("--policy-commit", required=True, help="Git commit identity attached to this replay execution")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    if policy.get("policy_id") != POLICY_ID or policy.get("status") != "FROZEN_PRE_REPLAY":
        raise SystemExit("frozen MLB replay policy identity/status mismatch")
    actual_blob = git_blob_sha(args.policy)
    if actual_blob != FROZEN_POLICY_GIT_BLOB_SHA:
        raise SystemExit(f"frozen MLB replay policy blob mismatch:{actual_blob}")

    rows = load_rows(args.input)
    validate_rows(rows)  # global rejection occurs before market partitioning
    by_market: dict[str, list[dict[str,str]]] = defaultdict(list)
    for row in rows:
        by_market[row["market"]].append(row)

    report = {
        "schema_version": 1,
        "policy_id": POLICY_ID,
        "policy_sha256": sha256_file(args.policy),
        "policy_git_blob_sha": actual_blob,
        "policy_git_commit": args.policy_commit,
        "input_sha256": sha256_file(args.input),
        "markets": {m: score(rs, validated=True) for m,rs in sorted(by_market.items())},
        "governance": {
            "third_party_predictions_imported": False,
            "historical_backfill_promoted": False,
            "model_p_created": False,
            "floor_derived": False,
            "eligibility_changed": False,
            "truth_gate_pass_granted": False,
            "staking_authority_granted": False,
            "official_status_granted": False,
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps({"status":"OK","markets":len(report["markets"]),"out":str(args.out)}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
