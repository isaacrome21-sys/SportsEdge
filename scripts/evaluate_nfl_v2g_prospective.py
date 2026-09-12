#!/usr/bin/env python3
"""Evaluate settled NFL V2G evidence only at frozen sample checkpoints.

Checkpoint membership is chronological and includes missing-close rows. A missing
capture therefore stays inside the first N observations as INCONCLUSIVE instead
of being silently replaced by a later game. Probability CLV is promotion-usable
only when every PAPER candidate in the checkpoint is comparable at the exact same
line; line CLV remains diagnostic only. Even a full pass is review-only.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

POLICY_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_PAPER_EVALUATION_POLICY_V1"
SETTLEMENT_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_SETTLEMENT_V1"
OUT_SCHEMA = "SPORTSEDGE_NFL_V2G_PROSPECTIVE_EVALUATION_V1"


def die(code: str) -> None:
    raise SystemExit(code)


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def clip_p(p: float) -> float:
    return min(max(float(p), 1e-9), 1.0 - 1e-9)


def calibration_fit(rows: list[dict[str, Any]]) -> tuple[float | None, float | None]:
    if len(rows) < 10:
        return None, None
    xs = [math.log(clip_p(float(r["model_probability"])) / (1.0 - clip_p(float(r["model_probability"])))) for r in rows]
    ys = [float(r["outcome"]) for r in rows]
    if min(ys) == max(ys):
        return None, None
    a, b = 0.0, 1.0
    for _ in range(60):
        probs = []
        for x in xs:
            z = max(min(a + b * x, 35.0), -35.0)
            probs.append(1.0 / (1.0 + math.exp(-z)))
        g0 = sum(y - p for y, p in zip(ys, probs))
        g1 = sum((y - p) * x for y, p, x in zip(ys, probs, xs))
        w = [p * (1.0 - p) for p in probs]
        i00 = sum(w)
        i01 = sum(v * x for v, x in zip(w, xs))
        i11 = sum(v * x * x for v, x in zip(w, xs))
        det = i00 * i11 - i01 * i01
        if abs(det) < 1e-12:
            return None, None
        da = (i11 * g0 - i01 * g1) / det
        db = (-i01 * g0 + i00 * g1) / det
        a += da
        b += db
        if max(abs(da), abs(db)) < 1e-10:
            break
    return a, b


def ece(rows: list[dict[str, Any]], bins: int = 10) -> float | None:
    if not rows:
        return None
    groups: list[list[tuple[float, float]]] = [[] for _ in range(bins)]
    for row in rows:
        p = min(max(float(row["model_probability"]), 0.0), 1.0)
        y = float(row["outcome"])
        idx = min(bins - 1, int(p * bins))
        groups[idx].append((p, y))
    total = len(rows)
    score = 0.0
    for group in groups:
        if group:
            avg_p = sum(x for x, _ in group) / len(group)
            avg_y = sum(y for _, y in group) / len(group)
            score += (len(group) / total) * abs(avg_p - avg_y)
    return score


def load_settlements(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted(root.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != SETTLEMENT_SCHEMA:
            continue
        if not str(value.get("status") or "").startswith("SETTLED_"):
            continue
        value = dict(value)
        value["_path"] = str(path)
        rows.append(value)
    rows.sort(key=lambda r: (str(r.get("kickoff_utc") or ""), str(r.get("game_id") or "")))
    return rows


def market_rows(settlements: list[dict[str, Any]], market: str) -> list[dict[str, Any]]:
    out = []
    for settlement in settlements:
        out.append({
            "game_id": settlement.get("game_id"),
            "kickoff_utc": settlement.get("kickoff_utc"),
            "predictive": (settlement.get("predictive_evaluation") or {}).get(market) or {"status": "INCONCLUSIVE_MISSING_CAPTURE"},
            "paper": (settlement.get("paper_evaluation") or {}).get(market) or {"status": "NO_PAPER_CANDIDATE"},
        })
    return out


def summarize_market(rows: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    sample = rows[:limit]
    scored = [x["predictive"] for x in sample if x["predictive"].get("status") == "SCORED"]
    pushes = [x for x in sample if x["predictive"].get("status") == "NOT_SCORED_PUSH"]
    missing = [x for x in sample if x["predictive"].get("status") == "INCONCLUSIVE_MISSING_CAPTURE"]
    other_unscored = [x for x in sample if x["predictive"].get("status") not in {"SCORED", "NOT_SCORED_PUSH", "INCONCLUSIVE_MISSING_CAPTURE"}]
    a, b = calibration_fit(scored)
    model_ll = mean([float(x["model_log_loss"]) for x in scored])
    market_ll = mean([float(x["closing_market_log_loss"]) for x in scored])
    model_brier = mean([float(x["model_brier"]) for x in scored])
    market_brier = mean([float(x["closing_market_brier"]) for x in scored])
    papers = [x["paper"] for x in sample if x["paper"].get("status") == "SETTLED_PAPER_CANDIDATE"]
    profits = [float(x["after_vig_profit_units"]) for x in papers]
    line_clv = [float(x["clv"]["line_clv"]) for x in papers if (x.get("clv") or {}).get("line_clv") is not None]
    prob_clv = [float(x["clv"]["probability_clv"]) for x in papers if (x.get("clv") or {}).get("probability_clv") is not None]
    probability_clv_complete = bool(papers) and len(prob_clv) == len(papers)
    beats = None if model_ll is None or market_ll is None else model_ll < market_ll
    return {
        "n": len(sample),
        "predictive_scorable_n": len(scored),
        "closing_line_push_n": len(pushes),
        "missing_close_n": len(missing),
        "other_unscored_n": len(other_unscored),
        "complete_close_evidence": len(missing) == 0 and len(other_unscored) == 0,
        "candidate_mean_log_loss": model_ll,
        "closing_market_mean_log_loss": market_ll,
        "candidate_beats_closing_market_log_loss": beats,
        "candidate_mean_brier": model_brier,
        "closing_market_mean_brier": market_brier,
        "calibration_intercept": a,
        "calibration_slope": b,
        "ece_10bin": ece(scored, 10),
        "paper_candidate_n": len(papers),
        "paper_after_vig_profit_units": sum(profits),
        "paper_after_vig_roi": mean(profits),
        "line_clv_n": len(line_clv),
        "mean_line_clv": mean(line_clv),
        "same_line_probability_clv_n": len(prob_clv),
        "probability_clv_complete": probability_clv_complete,
        "mean_probability_clv": mean(prob_clv) if probability_clv_complete else None,
        "sample_game_ids": [x["game_id"] for x in sample],
    }


def gate(value: bool | None) -> str:
    if value is None:
        return "INCONCLUSIVE"
    return "PASS" if value else "FAIL"


def evaluate(root: Path, policy_path: Path) -> dict[str, Any]:
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    if policy.get("schema_version") != POLICY_SCHEMA:
        die("NFL_V2G_EVAL_POLICY_SCHEMA_INVALID")
    metrics = policy.get("prospective_metrics") or {}
    if metrics.get("probability_clv_gate_requires_full_paper_candidate_comparability") is not True:
        die("NFL_V2G_EVAL_CLV_COMPARABILITY_POLICY_REQUIRED")
    if metrics.get("line_clv_is_diagnostic_only_for_probability_clv_gate") is not True:
        die("NFL_V2G_EVAL_LINE_CLV_DIAGNOSTIC_POLICY_REQUIRED")
    checkpoints = [int(x) for x in policy["checkpoints"]["fixed_settled_market_counts"]]
    minimum = int(policy["checkpoints"]["minimum_promotion_count"])
    settlements = load_settlements(root)
    by_market = {m: market_rows(settlements, m) for m in ("spread", "total")}
    observed = {m: len(v) for m, v in by_market.items()}
    common_n = min(observed.values()) if observed else 0
    reached = [x for x in checkpoints if x <= common_n]
    checkpoint = max(reached) if reached else None
    next_checkpoint = next((x for x in checkpoints if x > common_n), None)

    output: dict[str, Any] = {
        "schema_version": OUT_SCHEMA,
        "candidate_id": policy.get("candidate_id"),
        "observed_settled_n": observed,
        "common_settled_n": common_n,
        "checkpoint_evaluated": checkpoint,
        "next_checkpoint": next_checkpoint,
        "optional_stopping_allowed": False,
        "promotion_authority": False,
        "may_create_model_p": False,
        "truth_gate_pass_granted": False,
        "official_status_granted": False,
    }
    if checkpoint is None:
        output.update(status="PRECHECKPOINT_NO_GATE_EVALUATION", markets={}, gates={})
        return output

    markets = {m: summarize_market(by_market[m], checkpoint) for m in ("spread", "total")}
    gates: dict[str, Any] = {}
    all_gate_values: list[bool | None] = []
    for market, summary in markets.items():
        slope = summary["calibration_slope"]
        intercept = summary["calibration_intercept"]
        ece_value = summary["ece_10bin"]
        roi = summary["paper_after_vig_roi"]
        clv_complete = summary["probability_clv_complete"]
        clv = summary["mean_probability_clv"] if clv_complete else None
        checks: dict[str, bool | None] = {
            "count": summary["n"] >= minimum,
            "complete_close_evidence": summary["complete_close_evidence"],
            "beats_closing_market_log_loss": summary["candidate_beats_closing_market_log_loss"],
            "calibration_slope": None if slope is None else float(metrics["calibration_slope_min"]) <= slope <= float(metrics["calibration_slope_max"]),
            "calibration_intercept": None if intercept is None else abs(intercept) <= float(metrics["calibration_intercept_abs_max"]),
            "ece": None if ece_value is None else ece_value <= float(metrics["ece_max"]),
            "after_vig_roi": None if roi is None else roi >= float(metrics["after_vig_roi_threshold"]),
            "clv_comparability": True if clv_complete else None,
            "clv": None if clv is None else clv >= float(metrics["clv_probability_threshold"]),
        }
        gates[market] = {k: gate(v) for k, v in checks.items()}
        all_gate_values.extend(checks.values())

    if checkpoint < minimum:
        status = "FIXED_CHECKPOINT_DIAGNOSTIC_ONLY"
    elif all(v is True for v in all_gate_values):
        status = "REVIEW_ELIGIBLE_NO_AUTOPROMOTION"
    elif any(v is False for v in all_gate_values):
        status = "BLOCKED_PROSPECTIVE_GATES"
    else:
        status = "INCONCLUSIVE_PROSPECTIVE_GATES"
    output.update(status=status, markets=markets, gates=gates)
    return output


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--settlement-dir", type=Path, required=True)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = evaluate(args.settlement_dir, args.policy)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "checkpoint": result["checkpoint_evaluated"], "next_checkpoint": result["next_checkpoint"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
