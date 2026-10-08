#!/usr/bin/env python3
"""Fail-closed MLB pitcher-prop research fragility audit.

The 100k joint SCORE paths do not count as 100k independent pitcher outcomes.
This audit reports independent historical start support, an illustrative
Wilson interval, odds break-even, and a no-promotion decision. No odds are
used in probability fitting, and no model probabilities are modified.
"""
from __future__ import annotations

import argparse
import json
from math import isfinite, sqrt
from pathlib import Path


def wilson_interval(p: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if not (isfinite(p) and 0 <= p <= 1 and isfinite(n) and n > 0):
        raise ValueError("Invalid pitcher marginal probability/sample size")
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    radius = (z / denom) * sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, center - radius), min(1.0, center + radius)


def break_even(american: int) -> float:
    if -100 < american < 100 or american == 0:
        raise ValueError("Invalid American price")
    return 100 / (100 + american) if american > 0 else (-american) / (100 - american)


def audit(payload: dict) -> dict:
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Missing results")
    out = []
    for r in payload["results"]:
        if not str(r.get("engine_market", "")).startswith("PITCHER_"):
            continue
        if r.get("probability_source") != "CANONICAL_PITCHER_MARGINAL":
            raise ValueError("Pitcher marginal sourced from unsupported joint conditioning")
        meta = r.get("probability_meta") or {}
        n = float(meta.get("effective_history_starts", 0))
        p = float(r["research_p"])
        price = int(r["american_odds"])
        lo, hi = wilson_interval(p, n)
        flags = ["NOT_TEMPORALLY_VALIDATED"]
        if r.get("postseason_workload_adjusted") is not True:
            flags.append("POSTSEASON_WORKLOAD_NOT_ADJUSTED")
        if n < 30:
            flags.append("LOW_INDEPENDENT_START_SUPPORT")
        if float(r.get("ev_per_dollar", 0)) > 0.5:
            flags.append("EXTREME_RESEARCH_EV")
        if p >= 0.85:
            flags.append("HIGH_PROBABILITY_SENSITIVITY")
        out.append({
            "pitcher": r.get("pitcher_name"),
            "market": r.get("engine_market"),
            "side": r.get("side"),
            "line": r.get("line"),
            "american_odds": price,
            "research_p": p,
            "research_ev": r.get("ev_per_dollar"),
            "book_break_even_p": break_even(price),
            "independent_effective_starts": n,
            "wilson_95_heuristic": [lo, hi],
            "model_mc_paths_are_independent_pitcher_outcomes": False,
            "validated_probability_interval": False,
            "card_eligible": False,
            "flags": flags,
        })
    if not out:
        raise ValueError("No pitcher marginal results to audit")
    return {
        "type": "MLB_PITCHER_PROP_FRAGILITY_AUDIT_V1",
        "limitations": "Wilson bounds are descriptive approximations using effective start count, NOT calibrated uncertainty; postseason workload and market freshness remain unverified.",
        "pitcher_props_card_eligible": False,
        "pitcher_rows": len(out),
        "rows": out,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = audit(json.loads(Path(args.input).read_text(encoding="utf-8")))
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Pitcher fragility audit: {len(payload['rows'])} rows; all PASS/RESEARCH-ONLY")


if __name__ == "__main__":
    main()
