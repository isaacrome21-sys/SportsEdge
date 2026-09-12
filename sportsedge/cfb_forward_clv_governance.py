from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Mapping, Sequence

UTC = timezone.utc
WEBB_SIX_POINT = (
    -math.sqrt(1.5),
    -1.0,
    -math.sqrt(0.5),
    math.sqrt(0.5),
    1.0,
    math.sqrt(1.5),
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


def evaluate_first_play_attestation(
    *,
    quote_ts: datetime,
    first_play_ts: datetime | None,
    final_status_ts: datetime | None,
    sealed_at_ts: datetime,
    timestamp_precision_known: bool,
    timestamp_uncertainty_seconds: float | None,
    source_stable_at_seal: bool,
    stabilization_delay_hours: float = 12.0,
    max_uncertainty_seconds: float = 30.0,
    safety_margin_seconds: float = 30.0,
) -> AttestationDecision:
    """Apply CFB_FORWARD_CLV_POLICY_V1 v1.0.3 first-play rules.

    This function grants no promotion authority. It only classifies whether a raw
    close candidate survives the frozen posthoc actual-start attestation.
    """
    quote = _utc(quote_ts)
    sealed = _utc(sealed_at_ts)
    if final_status_ts is None:
        return AttestationDecision("INVALID_ATTESTATION_UNVERIFIED", "FINAL_STATUS_TIMESTAMP_MISSING", None, None)
    final_ts = _utc(final_status_ts)
    earliest_seal = final_ts + timedelta(hours=float(stabilization_delay_hours))
    if sealed < earliest_seal:
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
    """Fail closed: only explicit regular-season identity enters promotion inference."""
    text = " ".join(x for x in (season_type, notes) if x).strip().lower()
    postseason_tokens = ("postseason", "conference championship", "championship", "bowl", "playoff", "cfp")
    regular_tokens = ("regular", "regular season")
    if any(token in text for token in postseason_tokens):
        return "POSTSEASON_DIAGNOSTIC_ONLY"
    if any(token in text for token in regular_tokens):
        return "FBS_REGULAR_SEASON_ONLY"
    return "REGIME_UNVERIFIED_BLOCKED"


def eligible_regular_season_rows(rows: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    out = []
    for row in rows:
        if classify_cluster_regime(
            season_type=str(row.get("season_type") or ""),
            notes=str(row.get("regime_note") or ""),
        ) == "FBS_REGULAR_SEASON_ONLY":
            out.append(row)
    return out


def _mean(values: Sequence[float]) -> float:
    if not values:
        raise ForwardCLVGovernanceError("NO_OBSERVATIONS")
    return sum(values) / len(values)


def cluster_mean_clv(rows: Sequence[Mapping[str, object]]) -> dict[str, float]:
    by_cluster: dict[str, list[float]] = {}
    for row in rows:
        cluster = str(row.get("slate_date_ct") or "")
        if not cluster:
            raise ForwardCLVGovernanceError("SLATE_CLUSTER_MISSING")
        value = row.get("clv_pp")
        if value is None:
            raise ForwardCLVGovernanceError("CLV_MISSING_RETAINED_ROW_CANNOT_ENTER_NUMERIC_INFERENCE")
        by_cluster.setdefault(cluster, []).append(float(value))
    return {cluster: _mean(values) for cluster, values in by_cluster.items()}


def cr1_t_stat(cluster_means: Mapping[str, float]) -> float:
    values = list(cluster_means.values())
    g = len(values)
    if g < 2:
        return float("nan")
    mean = _mean(values)
    ss = sum((x - mean) ** 2 for x in values)
    variance = ss / (g - 1)
    se = math.sqrt(variance / g)
    if se == 0:
        return math.inf if mean > 0 else (-math.inf if mean < 0 else 0.0)
    return mean / se


def deterministic_bootstrap_seed(*, policy_sha256: str, market_ledger: str) -> int:
    digest = hashlib.sha256(f"CFB_FORWARD_CLV_BOOTSTRAP_V1|{policy_sha256}|{market_ledger}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False)


def wild_cluster_bootstrap_t(
    cluster_means: Mapping[str, float],
    *,
    policy_sha256: str,
    market_ledger: str,
    repetitions: int = 9999,
) -> dict[str, float | int]:
    """Deterministic null-imposed wild-cluster-bootstrap-t with Webb weights.

    The bootstrap is inference-only and cannot rescue a failed mean or CR1 gate.
    """
    values = [float(v) for _, v in sorted(cluster_means.items())]
    g = len(values)
    if g < 2:
        raise ForwardCLVGovernanceError("INSUFFICIENT_CLUSTERS_FOR_BOOTSTRAP")
    if repetitions <= 0:
        raise ForwardCLVGovernanceError("BOOTSTRAP_REPETITIONS_INVALID")
    observed_t = cr1_t_stat({str(i): v for i, v in enumerate(values)})
    centered = [v - _mean(values) for v in values]
    rng = random.Random(deterministic_bootstrap_seed(policy_sha256=policy_sha256, market_ledger=market_ledger))
    exceed = 0
    finite_observed = math.isfinite(observed_t)
    for _ in range(repetitions):
        boot = [centered[i] * rng.choice(WEBB_SIX_POINT) for i in range(g)]
        t_star = cr1_t_stat({str(i): v for i, v in enumerate(boot)})
        if finite_observed and math.isfinite(t_star) and abs(t_star) >= abs(observed_t):
            exceed += 1
        elif not finite_observed and not math.isfinite(t_star):
            exceed += 1
    p_value = (exceed + 1.0) / (repetitions + 1.0)
    return {
        "clusters": g,
        "repetitions": repetitions,
        "observed_t": observed_t,
        "two_sided_p": p_value,
    }


def evaluate_promotion_inference(
    rows: Sequence[Mapping[str, object]],
    *,
    policy_sha256: str,
    market_ledger: str,
    minimum_clusters: int = 12,
    mean_clv_pp_min: float = 0.5,
    cr1_t_min: float = 2.0,
    alpha: float = 0.05,
    repetitions: int = 9999,
) -> dict[str, object]:
    regular = eligible_regular_season_rows(rows)
    clusters = cluster_mean_clv(regular) if regular else {}
    g = len(clusters)
    mean_clv = _mean([float(r["clv_pp"]) for r in regular]) if regular else float("nan")
    t_stat = cr1_t_stat(clusters) if clusters else float("nan")
    result: dict[str, object] = {
        "promotion_authority": False,
        "eligible_regular_season_rows": len(regular),
        "eligible_regular_season_clusters": g,
        "mean_clv_pp": mean_clv,
        "cr1_t_stat": t_stat,
        "postseason_rows_excluded": len(rows) - len(regular),
        "bootstrap_two_sided_p": None,
        "inference_gate_pass": False,
        "blockers": [],
    }
    blockers: list[str] = result["blockers"]  # type: ignore[assignment]
    if g < minimum_clusters:
        blockers.append("MINIMUM_REGULAR_SEASON_SLATE_CLUSTERS_NOT_MET")
    if not math.isfinite(mean_clv) or mean_clv < mean_clv_pp_min:
        blockers.append("MEAN_CLV_GATE_FAILED")
    if not math.isfinite(t_stat) or t_stat < cr1_t_min:
        blockers.append("CR1_T_STAT_GATE_FAILED")
    if blockers:
        return result
    boot = wild_cluster_bootstrap_t(
        clusters,
        policy_sha256=policy_sha256,
        market_ledger=market_ledger,
        repetitions=repetitions,
    )
    result["bootstrap_two_sided_p"] = boot["two_sided_p"]
    if float(boot["two_sided_p"]) > alpha:
        blockers.append("WILD_CLUSTER_BOOTSTRAP_P_GATE_FAILED")
        return result
    result["inference_gate_pass"] = True
    return result
