"""Prospective Truth Gate evaluator for frozen NFL attempt-9 Model_P.

Evaluation is deterministic and fail-closed. Passing metrics alone never grants
deployment; external CI/PIT/floor attestations must also be supplied and the
result remains non-OFFICIAL until a separate deployment authority transition.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import mean
from typing import Any, Iterable, Mapping
import re

from .attempt9_inference import compute_clv_inference, load_frozen_inference_policy
from .attempt9_prospective import validate_decision
from .attempt9_prospective_evidence import validate_evidence

SCHEMA = "SPORTSEDGE_NFL_ATTEMPT9_PROSPECTIVE_TRUTH_GATE_V1"
_WEEK_RE = re.compile(r"^\d{4}_(\d{2})_")
_UNIQUENESS_POLICY = (
    "EARLIEST_VALID_DECISION_AT_UTC_THEN_SHA256_PER_GAME_MARKET_SELECTION"
)


def _utc(value: Any, code: str) -> datetime:
    try:
        out = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(code) from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError(code)
    return out.astimezone(timezone.utc)


def _roi(price: float, outcome: str) -> float:
    if outcome not in {"WIN", "LOSS"}:
        raise ValueError("NFL_A9_GATE_OUTCOME_UNSUPPORTED")
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
    evaluation_asof_utc: str | None = None,
) -> dict[str, Any]:
    thresholds=governance["nfl_game_market_precommitted_thresholds"]
    inference_policy=load_frozen_inference_policy()

    # Validate every submitted capture first. Exact duplicate hashes remain a
    # hard error. A second, different capture of the same game/market/selection
    # is not allowed to increase N: the earliest valid decision_at_utc wins,
    # with decision_sha256 as a deterministic tie-breaker. Evidence availability
    # is deliberately not part of this choice, so later settlement cannot alter
    # which decision counts.
    submitted_by_sha={}
    for d in decisions:
        sha=validate_decision(d,artifact=artifact)
        if sha in submitted_by_sha:
            raise ValueError("NFL_A9_GATE_DUPLICATE_DECISION")
        submitted_by_sha[sha]=dict(d)

    markets={d["market"] for d in submitted_by_sha.values()}
    if len(markets)>1:
        raise ValueError("NFL_A9_GATE_MIXED_MARKETS_EVALUATE_SEPARATELY")

    identities={(d["model_p_id"],d["model_p_artifact_sha256"],d["capture_code_git_sha"],d["training_source_sha256"]) for d in submitted_by_sha.values()}
    if len(identities)>1:
        raise ValueError("NFL_A9_GATE_IDENTITY_DRIFT")

    canonical_slots: dict[tuple[str, str, str], tuple[datetime, str, dict[str, Any]]] = {}
    for sha,d in submitted_by_sha.items():
        key=(str(d["game_id"]),str(d["market"]),str(d["selection"]))
        rank=(_utc(d["decision_at_utc"],"NFL_A9_GATE_DECISION_TIME_INVALID"),sha)
        current=canonical_slots.get(key)
        if current is None or rank < (current[0],current[1]):
            canonical_slots[key]=(rank[0],rank[1],d)
    by_sha={sha:d for _,sha,d in canonical_slots.values()}
    suppressed_shas=set(submitted_by_sha)-set(by_sha)

    paired=[]
    seen_evidence=set()
    suppressed_evidence_rows=0
    for e in evidence_rows:
        sha=str(e.get("decision_sha256") or "")
        if sha not in submitted_by_sha:
            raise ValueError("NFL_A9_GATE_ORPHAN_EVIDENCE")
        if sha in seen_evidence:
            raise ValueError("NFL_A9_GATE_DUPLICATE_EVIDENCE")
        seen_evidence.add(sha)
        d=submitted_by_sha[sha]
        validate_evidence(e,d,artifact=artifact)
        if sha in suppressed_shas:
            suppressed_evidence_rows += 1
            continue
        paired.append((d,dict(e)))

    paired_shas={str(e["decision_sha256"]) for _,e in paired}
    unpaired=[d for sha,d in by_sha.items() if sha not in paired_shas]
    asof=None
    if evaluation_asof_utc is not None:
        asof=_utc(evaluation_asof_utc,"NFL_A9_GATE_EVALUATION_ASOF_INVALID")
        pending=[d for d in unpaired if _utc(d["kickoff_utc"],"NFL_A9_GATE_KICKOFF_INVALID") > asof]
        missing=[d for d in unpaired if d not in pending]
    else:
        pending=[]
        missing=unpaired

    edge_floor=float(thresholds["minimum_model_edge_probability_points"])
    eligible=[(d,e) for d,e in paired if float(d["model_p"])-float(e["decision_novig_probability"]) >= edge_floor]
    weeks=set()
    eligible_weeks=[]
    for d,_ in eligible:
        m=_WEEK_RE.match(str(d["game_id"]))
        if not m: raise ValueError("NFL_A9_GATE_GAME_WEEK_UNPARSABLE")
        week=int(m.group(1))
        weeks.add(week)
        eligible_weeks.append(week)
    n=len(eligible)
    clvs=[float(e["clv"]) for _,e in eligible]
    rois=[_roi(float(d["price_american"]),str(e["outcome"])) for d,e in eligible]
    cal=[(float(d["model_p"]),1.0 if e["outcome"]=="WIN" else 0.0) for d,e in eligible]
    inference=compute_clv_inference(
        clvs,
        eligible_weeks,
        policy=inference_policy,
        thresholds=thresholds,
    )
    mean_clv=float(inference["mean_clv"])
    clv_t=float(inference["iid_t_stat"])
    if n>=2:
        slope,intercept,ece,maxdev=_calibration(cal)
        roi=mean(rois)
    else:
        slope=intercept=ece=maxdev=roi=float("nan")
    minimum_clusters=max(
        int(thresholds["minimum_distinct_week_clusters"]),
        int(inference_policy["clv_inference"]["minimum_distinct_clusters"]),
    )
    checks={
      # No canonical decision may silently disappear. Duplicate later captures
      # are reported separately but do not enter this denominator.
      "complete_evidence_coverage":bool(by_sha) and len(paired)==len(by_sha),
      "inference_policy_resolved":inference["policy_resolved"] is True,
      "minimum_promoted_decisions":n>=int(thresholds["minimum_promoted_decisions"]),
      "minimum_distinct_week_clusters":len(weeks)>=minimum_clusters,
      "minimum_mean_clv":n>=2 and mean_clv>=float(thresholds["minimum_mean_clv_probability_points"]),
      "minimum_clv_t_stat":inference["iid_pass"] is True,
      "minimum_clustered_clv_t_stat":inference["cluster_pass"] is True,
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
      "market":next(iter(markets)) if markets else None,
      "decision_uniqueness_policy":_UNIQUENESS_POLICY,
      "submitted_decisions":len(submitted_by_sha),
      "unique_game_market_selection_decisions":len(by_sha),
      "suppressed_duplicate_capture_decisions":len(suppressed_shas),
      "suppressed_duplicate_capture_evidence_rows":suppressed_evidence_rows,
      "pending_evidence_decisions":len(pending),
      "missing_evidence_decisions":len(missing),
      "evidence_status_asof_utc":asof.isoformat() if asof is not None else None,
      "evidence_status_basis":"EXPLICIT_ASOF_PREKICK_PENDING" if asof is not None else "ASOF_NOT_SUPPLIED_TREATED_MISSING_FAIL_CLOSED",
      "evidence_coverage":len(paired)/len(by_sha) if by_sha else 0.0,
      "clv_inference_status":"FROZEN_POLICY_BOUND_IID_AND_CR1_WEEK_CLUSTERED",
      "clv_inference_policy_git_blob_sha1":inference["policy_git_blob_sha1"],
      "eligible_decisions":n,
      "paired_decisions":len(paired),
      "distinct_week_clusters":len(weeks),
      "mean_clv":mean_clv,
      "clv_t_stat":clv_t,
      "clv_cluster_estimator":inference["cluster_estimator"],
      "clv_cluster_unit":inference["cluster_unit"],
      "clv_cluster_t_stat":inference["cluster_t_stat"],
      "clv_cluster_df":inference["cluster_df"],
      "clv_cluster_reference_critical":inference["cluster_reference_critical"],
      "clv_cluster_required_t":inference["cluster_required_t"],
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
