"""Shared projection-integrity controls across SportsEdge sports.

These utilities enforce pregame projection provenance, unresolved-participation
fail-closed behavior, immutable blend definitions, and correlation pricing from
joint simulation outcomes. They do not create model promotion evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from math import isfinite
from typing import Mapping, Sequence


DEFAULT_SIMULATIONS = 50_000


@dataclass(frozen=True)
class ProjectionComponent:
    source: str
    value: float
    weight: float
    as_of_utc: str
    version: str


@dataclass(frozen=True)
class ProjectionBlend:
    components: tuple[ProjectionComponent, ...]
    blended_value: float
    blend_hash: str
    promotion_evidence: bool = False


@dataclass(frozen=True)
class ParticipationState:
    status: str
    source: str
    as_of_utc: str


@dataclass(frozen=True)
class CorrelatedPrice:
    simulations: int
    legs: tuple[str, ...]
    joint_probability: float
    independent_probability: float
    correlation_multiplier: float
    promotion_evidence: bool = False


def build_projection_blend(components: Sequence[ProjectionComponent]) -> ProjectionBlend:
    if not components:
        raise ValueError("projection components required")
    total_weight = 0.0
    weighted = 0.0
    canonical = []
    for c in components:
        if not c.source or not c.version or not c.as_of_utc:
            raise ValueError("projection provenance required")
        if not isfinite(c.value):
            raise ValueError("projection value must be finite")
        if not isfinite(c.weight) or c.weight < 0:
            raise ValueError("projection weight must be finite and >= 0")
        total_weight += c.weight
        weighted += c.value * c.weight
        canonical.append({
            "source": c.source,
            "value": c.value,
            "weight": c.weight,
            "as_of_utc": c.as_of_utc,
            "version": c.version,
        })
    if abs(total_weight - 1.0) > 1e-12:
        raise ValueError("projection weights must sum to 1")
    payload = dumps(canonical, sort_keys=True, separators=(",", ":"))
    return ProjectionBlend(tuple(components), weighted, sha256(payload.encode()).hexdigest())


def participation_gate(state: ParticipationState) -> tuple[bool, tuple[str, ...]]:
    normalized = state.status.strip().upper()
    if normalized in {"ACTIVE", "CONFIRMED_IN", "AVAILABLE"}:
        return True, ()
    if normalized in {"OUT", "INACTIVE", "CONFIRMED_OUT"}:
        return False, ("PARTICIPANT_OUT",)
    return False, ("INPUT_MISSING_PARTICIPATION",)


def price_joint_from_simulations(
    outcomes: Mapping[str, Sequence[bool]],
    legs: Sequence[str],
    *,
    min_simulations: int = DEFAULT_SIMULATIONS,
) -> CorrelatedPrice:
    if len(legs) < 2:
        raise ValueError("at least two legs required")
    if len(set(legs)) != len(legs):
        raise ValueError("duplicate legs not allowed")
    missing = [leg for leg in legs if leg not in outcomes]
    if missing:
        raise ValueError(f"missing simulated leg outcomes: {missing}")
    lengths = {len(outcomes[leg]) for leg in legs}
    if len(lengths) != 1:
        raise ValueError("all legs must come from the same simulation population")
    simulations = lengths.pop()
    if simulations < min_simulations:
        raise ValueError(f"at least {min_simulations} joint simulations required")
    marginals = []
    joint = 0
    for leg in legs:
        seq = outcomes[leg]
        marginals.append(sum(bool(v) for v in seq) / simulations)
    for i in range(simulations):
        if all(bool(outcomes[leg][i]) for leg in legs):
            joint += 1
    joint_probability = joint / simulations
    independent_probability = 1.0
    for p in marginals:
        independent_probability *= p
    multiplier = joint_probability / independent_probability if independent_probability > 0 else 0.0
    return CorrelatedPrice(simulations, tuple(legs), joint_probability, independent_probability, multiplier)
