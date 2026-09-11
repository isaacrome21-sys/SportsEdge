from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Any, Sequence

ACCEPTED = {"BET"}
REJECTED = {"PASS", "QUARANTINE", "INSUFFICIENT_EVIDENCE", "UNVERIFIED_PRICE"}
DEFAULT_TIER_ORDER = ("ELITE", "STRONG", "GOOD", "LEAN")


@dataclass(frozen=True)
class TierMonotonicity:
    status: str
    score: float | None
    eligible_tiers: int
    adjacent_pairs: int


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
    tier_monotonicity_status: str
    tier_monotonicity_score: float | None
    quality_score: float | None
    status: str


def _mean(xs: list[float]) -> float | None:
    return None if not xs else sum(xs) / len(xs)


def _rate(flags: list[bool]) -> float | None:
    return None if not flags else sum(flags) / len(flags)


def tier_monotonicity(rows: Iterable[Mapping[str, Any]], *, tier_order: Sequence[str] = DEFAULT_TIER_ORDER,
                      minimum_per_tier: int = 150) -> TierMonotonicity:
    accepted = [r for r in rows if r.get("gate_decision") in ACCEPTED]
    summaries: list[tuple[str, float, float]] = []
    for tier in tier_order:
        group = [r for r in accepted if str(r.get("confidence_tier", "")).upper() == tier]
        usable = [r for r in group if r.get("clv") is not None and r.get("brier") is not None]
        if len(usable) < minimum_per_tier:
            return TierMonotonicity("INSUFFICIENT", None, len(summaries), max(0, len(summaries) - 1))
        summaries.append((tier, sum(float(r["clv"]) for r in usable) / len(usable),
                          sum(float(r["brier"]) for r in usable) / len(usable)))
    if len(summaries) < 2:
        return TierMonotonicity("INSUFFICIENT", None, len(summaries), 0)
    checks = []
    for higher, lower in zip(summaries, summaries[1:]):
        checks.append(higher[1] >= lower[1] and higher[2] <= lower[2])
    score = sum(checks) / len(checks)
    return TierMonotonicity("PASS" if score >= .80 else "FAIL", score, len(summaries), len(checks))


def evaluate_truth_gate(rows: Iterable[Mapping[str, Any]], *, good_clv_threshold: float = .015,
                        minimum_n: int = 300, clv_scale: float = .05,
                        tier_order: Sequence[str] = DEFAULT_TIER_ORDER,
                        minimum_per_tier: int = 150) -> GateMetrics:
    """Research-only counterfactual evaluator over immutable frozen opportunities."""
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
    mono = tier_monotonicity(data, tier_order=tier_order, minimum_per_tier=minimum_per_tier)
    score = None
    status = "INSUFFICIENT_EVIDENCE"
    if len(data) >= minimum_n and avoided is not None and false_neg is not None and delta is not None and mono.score is not None:
        clv_component = max(0.0, min(1.0, .5 + delta / (2 * clv_scale)))
        score = 100 * (.40 * avoided + .30 * (1 - false_neg) + .20 * clv_component + .10 * mono.score)
        status = "PUBLISHABLE_RESEARCH"
    return GateMetrics(len(data), len(accepted), len(rejected), len(a_clv) + len(r_clv), a_mean, r_mean,
                       _rate([x > 0 for x in a_clv]), _rate([x > 0 for x in r_clv]), avoided, false_neg,
                       selectivity, delta, mono.status, mono.score, score, status)
