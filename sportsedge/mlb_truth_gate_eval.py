from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any

ACCEPTED = {"BET"}
REJECTED = {"PASS", "QUARANTINE", "INSUFFICIENT_EVIDENCE", "UNVERIFIED_PRICE"}


@dataclass(frozen=True)
class GateMetrics:
    n_total: int
    n_accepted: int
    n_rejected: int
    n_with_clv: int
    accepted_mean_clv: float | None
    rejected_mean_clv: float | None
    accepted_beat_close_rate: float | None
    rejected_beat_close_rate: float | None
    avoided_bad_bets_rate: float | None
    good_pass_false_negative_rate: float | None
    selectivity_ratio: float
    clv_delta: float | None
    quality_score: float | None
    status: str


def _mean(xs: list[float]) -> float | None:
    return None if not xs else sum(xs) / len(xs)


def _rate(flags: list[bool]) -> float | None:
    return None if not flags else sum(flags) / len(flags)


def evaluate_truth_gate(rows: Iterable[Mapping[str, Any]], *,
                        good_clv_threshold: float = .015,
                        minimum_n: int = 300,
                        clv_scale: float = .05,
                        tier_monotonicity_score: float | None = None) -> GateMetrics:
    """Research-only counterfactual evaluator over immutable frozen opportunities.

    CLV is expected as probability-space CLV (positive = beat close). Rows without
    reliable closing prices are excluded from CLV-derived metrics.
    """
    data = list(rows)
    accepted = [r for r in data if r.get("gate_decision") in ACCEPTED]
    rejected = [r for r in data if r.get("gate_decision") in REJECTED]
    a_clv = [float(r["clv"]) for r in accepted if r.get("clv") is not None]
    r_clv = [float(r["clv"]) for r in rejected if r.get("clv") is not None]
    a_mean, r_mean = _mean(a_clv), _mean(r_clv)
    avoided = _rate([x < 0 for x in r_clv])
    false_neg = _rate([x >= good_clv_threshold for x in r_clv])
    delta = None if a_mean is None or r_mean is None else a_mean - r_mean
    selectivity = 0.0 if not data else len(rejected) / len(data)
    score = None
    status = "INSUFFICIENT_EVIDENCE"
    if len(data) >= minimum_n and avoided is not None and false_neg is not None and delta is not None and tier_monotonicity_score is not None:
        clv_component = max(0.0, min(1.0, .5 + delta / (2 * clv_scale)))
        tier = max(0.0, min(1.0, tier_monotonicity_score))
        score = 100 * (.40 * avoided + .30 * (1 - false_neg) + .20 * clv_component + .10 * tier)
        status = "PUBLISHABLE_RESEARCH"
    return GateMetrics(
        n_total=len(data), n_accepted=len(accepted), n_rejected=len(rejected),
        n_with_clv=len(a_clv) + len(r_clv), accepted_mean_clv=a_mean,
        rejected_mean_clv=r_mean, accepted_beat_close_rate=_rate([x > 0 for x in a_clv]),
        rejected_beat_close_rate=_rate([x > 0 for x in r_clv]),
        avoided_bad_bets_rate=avoided, good_pass_false_negative_rate=false_neg,
        selectivity_ratio=selectivity, clv_delta=delta, quality_score=score, status=status,
    )
