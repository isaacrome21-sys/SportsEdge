from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

UTC = timezone.utc
WEBB_SIX_POINT = (
    -math.sqrt(1.5), -1.0, -math.sqrt(0.5),
    math.sqrt(0.5), 1.0, math.sqrt(1.5),
)

class ForwardCLVGovernanceError(ValueError):
    pass

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ForwardCLVGovernanceError("TIMESTAMP_TIMEZONE_REQUIRED")
    return value.astimezone(UTC)

@dataclass(frozen=True)
class AttestationDecision:
    status: str
    reason: str
    seconds_before_first_play: float | None
    required_margin_seconds: float | None

def evaluate_first_play_attestation(*, quote_ts: datetime, first_play_ts: datetime | None,
    final_status_ts: datetime | None, sealed_at_ts: datetime,
    timestamp_precision_known: bool, timestamp_uncertainty_seconds: float | None,
    source_stable_at_seal: bool, stabilization_delay_hours: float = 12.0,
    max_uncertainty_seconds: float = 30.0, safety_margin_seconds: float = 30.0) -> AttestationDecision:
    quote = _utc(quote_ts); sealed = _utc(sealed_at_ts)
    if final_status_ts is None:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "FINAL_STATUS_TIMESTAMP_MISSING", None, None)
    final_ts = _utc(final_status_ts)
    if sealed < final_ts + timedelta(hours=float(stabilization_delay_hours)):
        return AttestationDecision("PENDING_STABILIZATION", "STABILIZATION_DELAY_NOT_MET", None, None)
    if first_play_ts is None:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "FIRST_PLAY_TIMESTAMP_MISSING", None, None)
    first_play = _utc(first_play_ts)
    if not timestamp_precision_known:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "TIMESTAMP_PRECISION_UNKNOWN", None, None)
    if timestamp_uncertainty_seconds is None:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "TIMESTAMP_UNCERTAINTY_MISSING", None, None)
    uncertainty = float(timestamp_uncertainty_seconds)
    if not math.isfinite(uncertainty) or uncertainty < 0:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "TIMESTAMP_UNCERTAINTY_INVALID", None, None)
    if uncertainty > float(max_uncertainty_seconds):
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "TIMESTAMP_UNCERTAINTY_EXCEEDS_MAX", None, None)
    if not source_stable_at_seal:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "ATTESTATION_SOURCE_UNSTABLE_AT_SEAL", None, None)
    seconds_before = (first_play - quote).total_seconds()
    required_margin = uncertainty + float(safety_margin_seconds)
    if seconds_before <= 0:
        return AttestationDecision("INVALID_POST_START", "QUOTE_AT_OR_AFTER_FIRST_PLAY", seconds_before, required_margin)
    if seconds_before < required_margin:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "QUOTE_INSIDE_UNCERTAINTY_SAFETY_MARGIN", seconds_before, required_margin)
    return AttestationDecision("VALID_ATTESTED_PRE_START", "SURVIVES_FROZEN_FIRST_PLAY_RULE", seconds_before, required_margin)

def classify_cluster_regime(*, season_type: str | None = None, notes: str | None = None) -> str:
    text = " ".join(x for x in (season_type, notes) if x).strip().lower()
    if any(t in text for t in ("postseason", "conference championship", "championship", "bowl", "playoff", "cfp")):
        return "POSTSEASON_DIAGNOSTIC_ONLY"
    if any(t in text for t in ("regular", "regular season")):
        return "FBS_REGULAR_SEASON_ONLY"
    return "REGIME_UNVERIFIED_BLOCKED"

def eligible_regular_season_rows(rows: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    return [r for r in rows if classify_cluster_regime(season_type=str(r.get("season_type") or ""), notes=str(r.get("regime_note") or "")) == "FBS_REGULAR_SEASON_ONLY"]

def _mean(values: Sequence[float]) -> float:
    if not values: raise ForwardCLVGovernanceError("NO_OBSERVATIONS")
    return sum(values) / len(values)

def cluster_mean_clv(rows: Sequence[Mapping[str, object]]) -> dict[str, float]:
    by: dict[str, list[float]] = {}
    for row in rows:
        cluster = str(row.get("slate_date_ct") or "")
        if not cluster: raise ForwardCLVGovernanceError("SLATE_CLUSTER_MISSING")
        if row.get("clv_pp") is None: raise ForwardCLVGovernanceError("CLV_MISSING_RETAINED_ROW_CANNOT_ENTER_NUMERIC_INFERENCE")
        by.setdefault(cluster, []).append(float(row["clv_pp"]))
    return {k: _mean(v) for k, v in by.items()}

def cr1_t_stat(cluster_means: Mapping[str, float]) -> float:
    values=list(cluster_means.values()); g=len(values)
    if g < 2: return float("nan")
    mean=_mean(values); variance=sum((x-mean)**2 for x in values)/(g-1); se=math.sqrt(variance/g)
    if se == 0: return math.inf if mean > 0 else (-math.inf if mean < 0 else 0.0)
    return mean/se

def deterministic_bootstrap_seed(*, policy_sha256: str, market_ledger: str) -> int:
    d=hashlib.sha256(f"CFB_FORWARD_CLV_BOOTSTRAP_V1|{policy_sha256}|{market_ledger}".encode()).digest()
    return int.from_bytes(d[:8], "big")

def wild_cluster_bootstrap_t(cluster_means: Mapping[str,float], *, policy_sha256:str, market_ledger:str, repetitions:int=9999) -> dict[str,float|int]:
    values=[float(v) for _,v in sorted(cluster_means.items())]; g=len(values)
    if g<2: raise ForwardCLVGovernanceError("INSUFFICIENT_CLUSTERS_FOR_BOOTSTRAP")
    if repetitions<=0: raise ForwardCLVGovernanceError("BOOTSTRAP_REPETITIONS_INVALID")
    observed=cr1_t_stat({str(i):v for i,v in enumerate(values)}); centered=[v-_mean(values) for v in values]
    rng=random.Random(deterministic_bootstrap_seed(policy_sha256=policy_sha256, market_ledger=market_ledger)); exceed=0
    for _ in range(repetitions):
        boot=[centered[i]*rng.choice(WEBB_SIX_POINT) for i in range(g)]; t=cr1_t_stat({str(i):v for i,v in enumerate(boot)})
        if math.isfinite(observed) and math.isfinite(t) and abs(t)>=abs(observed): exceed+=1
        elif not math.isfinite(observed) and not math.isfinite(t): exceed+=1
    return {"clusters":g,"repetitions":repetitions,"observed_t":observed,"two_sided_p":(exceed+1.0)/(repetitions+1.0)}

def evaluate_promotion_inference(rows: Sequence[Mapping[str,object]], *, policy_sha256:str, market_ledger:str,
    minimum_clusters:int=12, mean_clv_pp_min:float=0.5, cr1_t_min:float=2.0, alpha:float=0.05, repetitions:int=9999) -> dict[str,object]:
    regular=eligible_regular_season_rows(rows); clusters=cluster_mean_clv(regular) if regular else {}; g=len(clusters)
    mean=_mean([float(r["clv_pp"]) for r in regular]) if regular else float("nan"); t=cr1_t_stat(clusters) if clusters else float("nan")
    out={"promotion_authority":False,"eligible_regular_season_rows":len(regular),"eligible_regular_season_clusters":g,"mean_clv_pp":mean,"cr1_t_stat":t,"postseason_rows_excluded":len(rows)-len(regular),"bootstrap_two_sided_p":None,"inference_gate_pass":False,"blockers":[]}
    blockers=out["blockers"]
    if g<minimum_clusters: blockers.append("MINIMUM_REGULAR_SEASON_SLATE_CLUSTERS_NOT_MET")
    if not math.isfinite(mean) or mean<mean_clv_pp_min: blockers.append("MEAN_CLV_GATE_FAILED")
    if not math.isfinite(t) or t<cr1_t_min: blockers.append("CR1_T_STAT_GATE_FAILED")
    if blockers: return out
    boot=wild_cluster_bootstrap_t(clusters,policy_sha256=policy_sha256,market_ledger=market_ledger,repetitions=repetitions); out["bootstrap_two_sided_p"]=boot["two_sided_p"]
    if float(boot["two_sided_p"])>alpha: blockers.append("WILD_CLUSTER_BOOTSTRAP_P_GATE_FAILED"); return out
    out["inference_gate_pass"]=True; return out
