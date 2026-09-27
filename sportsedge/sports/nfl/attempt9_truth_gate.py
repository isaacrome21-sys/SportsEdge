"""Prospective Truth Gate evaluator for frozen NFL attempt-9 Model_P.

Evaluation is deterministic and fail-closed. Passing metrics alone never grants
deployment; external CI/PIT/floor attestations must also be supplied and the
result remains non-OFFICIAL until a separate deployment authority transition.
"""
from __future__ import annotations

from math import sqrt
from statistics import mean, stdev
from typing import Any, Iterable, Mapping
import re

from .attempt9_prospective import validate_decision
from .attempt9_prospective_evidence import validate_evidence

SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_PROSPECTIVE_TRUTH_GATE_V1"
_WEEK_RE = re.compile(r"^\d{4}_(\d{2})_")


def _roi(price: float, outcome: str) -> float:
    if outcome == "LOSS":
        return -1.0
    return price / 100.0 if price > 0 else 100.0 / (-price)


def _calibration(rows: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    xs=[p for p,_ in rows]; ys=[y for _,y in rows]
    mx,my=mean(xs),mean(ys)
    denom=sum((x-mx)**2 for x in xs)
    if denom <= 0:
        return float("nan"),float("nan"),float("inf"),float("inf")
    slope=sum((x-mx)*(y-my) for x,y in rows)/denom
    intercept=my-slope*mx
    bins=[[] for _ in range(10)]
    for p,y in rows:
        bins[min(9,max(0,int(p*10)))].append((p,y))
    weighted=0.0; maxdev=0.0
    for b in bins:
        if not b: continue
        dev=abs(mean(y for _,y in b)-mean(p for p,_ in b))
        weighted += len(b)*dev
        maxdev=max(maxdev,dev)
    return slope,intercept,weighted/len(rows),maxdev


def evaluate_truth_gate(
    decisions: Iterable[Mapping[str, Any]],
    evidence_rows: Iterable[Mapping[str, Any]],
    *,
    artifact: Mapping[str, Any],
    governance: Mapping[str, Any],
    ci_attested: bool,
    pit_integrity_verified: bool,
    truth_gate_floor_verified: bool,
) -> dict[str, Any]:
    thresholds=governance["nfl_game_market_precommitted_thresholds"]
    by_sha={}
    for d in decisions:
        sha=validate_decision(d,artifact=artifact)
        if sha in by_sha:
            raise ValueError("NFL_A9_GATE_DUPLICATE_DECISION")
        by_sha[sha]=dict(d)
    paired=[]
    for e in evidence_rows:
        sha=str(e.get("decision_sha256") or "")
        if sha not in by_sha:
            raise ValueError("NFL_A9_GATE_ORPHAN_EVIDENCE")
        d=by_sha[sha]
        validate_evidence(e,d,artifact=artifact)
        paired.append((d,dict(e)))
    identities={(d["model_p_id"],d["model_p_artifact_sha256"],d["capture_code_git_sha"],d["training_source_sha256"]) for d,_ in paired}
    if len(identities)>1:
        raise ValueError("NFL_A9_GATE_IDENTITY_DRIFT")
    edge_floor=float(thresholds["minimum_model_edge_probability_points"])
    eligible=[(d,e) for d,e in paired if float(d["model_p"])-float(e["decision_novig_probability"]) >= edge_floor]
    weeks=set()
    for d,_ in eligible:
        m=_WEEK_RE.match(str(d["game_id"]))
        if not m: raise ValueError("NFL_A9_GATE_GAME_WEEK_UNPARSABLE")
        weeks.add(int(m.group(1)))
    n=len(eligible)
    clvs=[float(e["clv"]) for _,e in eligible]
    rois=[_roi(float(d["price_american"]),str(e["outcome"])) for d,e in eligible]
    cal=[(float(d["model_p"]),1.0 if e["outcome"]=="WIN" else 0.0) for d,e in eligible]
    if n>=2:
        mean_clv=mean(clvs); sd=stdev(clvs); clv_t=float("inf") if sd==0 and mean_clv>0 else (mean_clv/(sd/sqrt(n)) if sd>0 else 0.0)
    else:
        mean_clv=float("nan"); clv_t=float("nan")
    if n>=2:
        slope,intercept,ece,maxdev=_calibration(cal)
        roi=mean(rois)
    else:
        slope=intercept=ece=maxdev=roi=float("nan")
    checks={
      "minimum_promoted_decisions":n>=int(thresholds["minimum_promoted_decisions"]),
      "minimum_distinct_week_clusters":len(weeks)>=int(thresholds["minimum_distinct_week_clusters"]),
      "minimum_mean_clv":n>=2 and mean_clv>=float(thresholds["minimum_mean_clv_probability_points"]),
      "minimum_clv_t_stat":n>=2 and clv_t>=float(thresholds["minimum_clv_t_stat"]),
      "minimum_after_vig_roi":n>=2 and roi>=float(thresholds["minimum_after_vig_roi"]),
      "calibration_slope":n>=2 and float(thresholds["calibration_slope_min"])<=slope<=float(thresholds["calibration_slope_max"]),
      "calibration_intercept":n>=2 and abs(intercept)<=float(thresholds["calibration_intercept_abs_max"]),
      "ece":n>=2 and ece<=float(thresholds["ece_max"]),
      "max_nonempty_bin_deviation":n>=2 and maxdev<=float(thresholds["max_nonempty_bin_deviation"]),
      "exact_identity_binding":len(identities)==1 and n>0,
      "ci_attested":ci_attested is True,
      "pit_integrity_verified":pit_integrity_verified is True,
      "truth_gate_floor_verified":truth_gate_floor_verified is True,
    }
    passed=all(checks.values())
    return {
      "schema_version":SCHEMA,
      "status":"PASS_NOT_DEPLOYED" if passed else "BLOCKED",
      "eligible_decisions":n,
      "paired_decisions":len(paired),
      "distinct_week_clusters":len(weeks),
      "mean_clv":mean_clv,
      "clv_t_stat":clv_t,
      "after_vig_roi":roi,
      "calibration_slope":slope,
      "calibration_intercept":intercept,
      "ece":ece,
      "max_nonempty_bin_deviation":maxdev,
      "checks":checks,
      "promotion_authority":False,
      "deployed":False,
      "official_authority":False,
      "staking_authority":False,
    }
