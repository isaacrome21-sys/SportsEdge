"""Structural completion-gap ledger over the cross-sport readiness inventory.

Lists each canonical market that lacks a priced path or forward-test config,
the score area it affects and whether it is buildable now or blocked. It is
structural only: it awards no score points, confers no validation and grants
no play authority. Validation gaps are never buildable.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from scripts.audit_cross_sport_accuracy_readiness import accuracy_readiness

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "completion_gap_policy_v1.json"
SCHEMA = "SPORTSEDGE_COMPLETION_GAP_LEDGER_V1"

_BLOCKERS = {
    "NO_ENGINE": ("ENGINES", "BUILDABLE"),
    "NO_VALIDATION": ("VALIDATION", "BLOCKED_FORWARD_VERDICT_REQUIRED"),
    "NO_DATA": ("ENGINES", "BLOCKED_MISSING_DATA"),
    "NO_QUOTE": ("INFRASTRUCTURE", "BLOCKED_MISSING_QUOTE"),
}


class LedgerRefusal(ValueError):
    pass


def classify(row: dict, policy: dict) -> dict | None:
    if row.get("validated_accuracy_in_this_audit") is not False:
        raise LedgerRefusal("INPUT_CLAIMS_VALIDATION")
    blocker, readiness = row.get("blocker"), row.get("readiness")
    if blocker is None:
        if readiness == "RESEARCH_PRICED_NOT_VALIDATED":
            return None
        if readiness != "NO_FORWARD_TEST_CONFIG":
            raise LedgerRefusal(f"UNKNOWN_READINESS:{readiness}")
        area, status = "INFRASTRUCTURE", "BUILDABLE_NEEDS_SIBLING_RECONCILIATION"
    elif blocker in _BLOCKERS:
        area, status = _BLOCKERS[blocker]
    else:
        raise LedgerRefusal(f"UNKNOWN_BLOCKER:{blocker}")
    paused = row["market"] in policy.get("paused_markets", {}).get(row["sport"], [])
    if paused and status.startswith("BUILDABLE"):
        status = "BLOCKED_RULING_6_FOCUS_PAUSE"
    held = row["market"] in policy.get("owner_held_markets", {}).get(row["sport"], [])
    if held and status.startswith("BUILDABLE"):
        status = "BLOCKED_OWNER_HOLD"
    return {"sport": row["sport"], "market": row["market"], "blocker": blocker,
            "readiness": readiness, "score_area": area, "status": status}


def gap_ledger(*, root: Path = ROOT) -> dict:
    policy = json.loads((root / "config" / "completion_gap_policy_v1.json").read_text(encoding="utf-8"))
    if policy.get("schema") != "SPORTSEDGE_COMPLETION_GAP_POLICY_V1":
        raise LedgerRefusal("POLICY_SCHEMA")
    report = accuracy_readiness(root=root)
    if report.get("validated_families_conferred") != 0 or report.get("play_authority_conferred") is not False:
        raise LedgerRefusal("UPSTREAM_CONFERS_AUTHORITY")
    gaps = [g for g in (classify(r, policy) for r in report["canonical_markets"]) if g]
    gaps.sort(key=lambda g: (g["score_area"], g["status"], g["sport"], g["market"]))
    return {
        "schema": SCHEMA,
        "scope": "CANONICAL_MLB_NFL_MARKETS_ONLY",
        "gaps": gaps,
        "counts_by_status": dict(sorted(Counter(g["status"] for g in gaps).items())),
        "counts_by_area": dict(sorted(Counter(g["score_area"] for g in gaps).items())),
        "score_points_awarded": None,
        "validated_families_conferred": 0,
        "play_authority_conferred": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path)
    a = p.parse_args()
    text = json.dumps(gap_ledger(), indent=2, sort_keys=True) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
