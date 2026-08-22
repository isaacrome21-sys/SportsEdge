"""Candidate-generation layer for MLB props.

This module ranks situations worth pricing. It does NOT create a bet, estimate
EV, or count as promotion evidence. Recent hit rates are descriptive filters,
not standalone probabilities.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence


class CandidateType(str, Enum):
    HITTER_HIT = "HITTER_HIT"
    PITCHER_HITS_ALLOWED = "PITCHER_HITS_ALLOWED"
    PITCHER_K_OVER = "PITCHER_K_OVER"
    PITCHER_K_UNDER = "PITCHER_K_UNDER"
    PITCHER_OUTS_OVER = "PITCHER_OUTS_OVER"
    BULLPEN_ATTACK = "BULLPEN_ATTACK"


@dataclass(frozen=True)
class Signal:
    name: str
    value: float
    weight: float
    available: bool = True


@dataclass(frozen=True)
class Candidate:
    candidate_type: CandidateType
    subject: str
    opponent: str
    score: float
    coverage: float
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    promotion_evidence: bool = False


def _bounded(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


def score_signals(signals: Sequence[Signal], *, min_coverage: float = 0.60) -> tuple[float, float]:
    """Weighted 0..1 score plus feature coverage.

    Missing inputs reduce coverage rather than being silently imputed as good.
    """
    total_weight = sum(max(0.0, s.weight) for s in signals)
    if total_weight <= 0:
        raise ValueError("positive signal weight required")
    observed = [s for s in signals if s.available]
    observed_weight = sum(max(0.0, s.weight) for s in observed)
    coverage = observed_weight / total_weight
    if coverage < min_coverage:
        return 0.0, coverage
    score = sum(_bounded(s.value) * max(0.0, s.weight) for s in observed) / observed_weight
    return score, coverage


def make_candidate(
    candidate_type: CandidateType,
    subject: str,
    opponent: str,
    signals: Sequence[Signal],
    *,
    threshold: float = 0.66,
    min_coverage: float = 0.60,
    warnings: Sequence[str] = (),
) -> Candidate | None:
    score, coverage = score_signals(signals, min_coverage=min_coverage)
    if coverage < min_coverage or score < threshold:
        return None
    ranked = sorted((s for s in signals if s.available), key=lambda s: s.value * s.weight, reverse=True)
    reasons = tuple(f"{s.name}={s.value:.3f}" for s in ranked[:4])
    return Candidate(candidate_type, subject, opponent, score, coverage, reasons, tuple(warnings))


def hitter_hit_signals(f: Mapping[str, float]) -> tuple[Signal, ...]:
    return (
        Signal("projected_pa", f.get("projected_pa_score", 0), 1.25, "projected_pa_score" in f),
        Signal("lineup_slot", f.get("lineup_slot_score", 0), 0.80, "lineup_slot_score" in f),
        Signal("batter_contact", f.get("contact_score", 0), 1.15, "contact_score" in f),
        Signal("platoon", f.get("platoon_score", 0), 0.75, "platoon_score" in f),
        Signal("sp_xba_allowed", f.get("sp_xba_allowed_score", 0), 1.10, "sp_xba_allowed_score" in f),
        Signal("bullpen_quality", f.get("bullpen_attack_score", 0), 0.85, "bullpen_attack_score" in f),
        Signal("park_weather", f.get("environment_score", 0), 0.55, "environment_score" in f),
        Signal("recent_hit_rate", f.get("recent_hit_rate", 0), 0.35, "recent_hit_rate" in f),
    )


def pitcher_hits_allowed_signals(f: Mapping[str, float]) -> tuple[Signal, ...]:
    return (
        Signal("batters_faced", f.get("bf_score", 0), 1.15, "bf_score" in f),
        Signal("xba_allowed", f.get("xba_allowed_score", 0), 1.25, "xba_allowed_score" in f),
        Signal("hard_hit_allowed", f.get("hard_hit_score", 0), 0.95, "hard_hit_score" in f),
        Signal("barrel_allowed", f.get("barrel_score", 0), 0.80, "barrel_score" in f),
        Signal("opponent_contact", f.get("opp_contact_score", 0), 1.10, "opp_contact_score" in f),
        Signal("opponent_vs_hand", f.get("opp_hand_score", 0), 0.90, "opp_hand_score" in f),
        Signal("recent_4plus", f.get("recent_4plus_rate", 0), 0.30, "recent_4plus_rate" in f),
    )


def pitcher_k_signals(f: Mapping[str, float], *, under: bool = False) -> tuple[Signal, ...]:
    vals = {
        "k_rate": f.get("k_rate_score", 0),
        "whiff": f.get("whiff_score", 0),
        "chase": f.get("chase_score", 0),
        "opp_k": f.get("opp_k_score", 0),
        "pitch_count": f.get("pitch_count_score", 0),
        "workload": f.get("workload_score", 0),
    }
    if under:
        vals = {k: 1.0 - _bounded(v) for k, v in vals.items()}
    return tuple(Signal(k, v, w, key in f) for (k, v), (key, w) in zip(vals.items(), (
        ("k_rate_score", 1.25), ("whiff_score", 1.10), ("chase_score", .75),
        ("opp_k_score", 1.10), ("pitch_count_score", .95), ("workload_score", 1.00))))


def bullpen_attack_signals(f: Mapping[str, float]) -> tuple[Signal, ...]:
    return (
        Signal("season_xfip", f.get("season_xfip_score", 0), 1.05, "season_xfip_score" in f),
        Signal("last14_xfip", f.get("last14_xfip_score", 0), 0.70, "last14_xfip_score" in f),
        Signal("availability", f.get("reliever_unavailable_score", 0), 1.20, "reliever_unavailable_score" in f),
        Signal("back_to_back", f.get("back_to_back_score", 0), 0.90, "back_to_back_score" in f),
        Signal("platoon_fit", f.get("platoon_fit_score", 0), 0.70, "platoon_fit_score" in f),
        Signal("last7_era", f.get("last7_era_score", 0), 0.20, "last7_era_score" in f),
    )
