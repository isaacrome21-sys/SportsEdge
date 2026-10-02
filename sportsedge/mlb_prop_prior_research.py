"""Research-only long-window prior candidate for MLB props.

This module MUST NOT be imported by production prop engines.  It exists to compare
an anchored candidate against the currently frozen Jeffreys-only baseline on
strictly chronological held-out rows before any promotion PR is considered.

The candidate treats recent observations as likelihood evidence and an older,
strictly-prior window as a data-derived Dirichlet prior.  Sportsbook prices are
never prior inputs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from typing import Any, Mapping, Sequence

from sportsedge.mlb_empirical_bayes import JEFFREYS_ALPHA

LONG_WINDOW_PRIOR_NAME = "STRICT_PRIOR_LONG_WINDOW_DIRICHLET_V1"


class PropPriorResearchError(ValueError):
    pass


def _parse_utc(value: Any) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise PropPriorResearchError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PropPriorResearchError(f"timestamp must be offset-aware: {value!r}")
    return parsed.astimezone(timezone.utc)


def _validate_mass(name: str, values: Mapping[str, float], active: Sequence[str]) -> dict[str, float]:
    out = {key: float(values.get(key, 0.0)) for key in ("over", "under", "push")}
    if any((not isfinite(value)) or value < 0.0 or value > 1.0 for value in out.values()):
        raise PropPriorResearchError(f"{name} masses must be finite probabilities")
    if abs(sum(out.values()) - 1.0) > 1e-9:
        raise PropPriorResearchError(f"{name} mass does not conserve")
    inactive = set(out) - set(active)
    if any(out[key] > 1e-12 for key in inactive):
        raise PropPriorResearchError(f"{name} carries mass on an inactive settlement")
    return out


def long_window_posterior_settlement_mass(
    *,
    recent_mass: Mapping[str, float],
    recent_effective_n: float,
    prior_mass: Mapping[str, float],
    prior_effective_n: float,
    has_push: bool,
    prior_strength_cap: float,
    feasible: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Return the research candidate posterior predictive settlement mass.

    ``prior_mass`` must come only from observations older than the recent window
    and strictly before the target event.  The data-derived prior contributes at
    most ``prior_strength_cap`` pseudo-observations, preventing a long career
    history from overwhelming current form.  A Jeffreys 0.5 floor remains on each
    reachable category so finite support is retained.
    """
    for label, value in (
        ("recent_effective_n", recent_effective_n),
        ("prior_effective_n", prior_effective_n),
        ("prior_strength_cap", prior_strength_cap),
    ):
        number = float(value)
        if not isfinite(number) or number <= 0.0:
            raise PropPriorResearchError(f"{label} must be finite and positive")

    candidates = ("over", "under", "push") if has_push else ("over", "under")
    reachable = {
        name: True if feasible is None else bool(feasible.get(name, True))
        for name in candidates
    }
    active = tuple(name for name in candidates if reachable[name])
    if not active:
        raise PropPriorResearchError("no feasible settlement category")

    recent = _validate_mass("recent", recent_mass, active)
    older = _validate_mass("prior", prior_mass, active)
    prior_strength = min(float(prior_effective_n), float(prior_strength_cap))

    alpha = {
        name: (
            JEFFREYS_ALPHA
            + float(recent_effective_n) * recent[name]
            + prior_strength * older[name]
        )
        for name in active
    }
    total_alpha = sum(alpha.values())
    posterior = {name: alpha[name] / total_alpha for name in active}
    for name in ("over", "under", "push"):
        posterior.setdefault(name, 0.0)

    return {
        "p_over": posterior["over"],
        "p_under": posterior["under"],
        "p_push": posterior["push"],
        "recent_effective_sample_size": float(recent_effective_n),
        "prior_effective_sample_size": float(prior_effective_n),
        "prior_strength": prior_strength,
        "prior_strength_cap": float(prior_strength_cap),
        "prior_over": older["over"],
        "prior_under": older["under"],
        "prior_push": older["push"],
        "prior": LONG_WINDOW_PRIOR_NAME,
        "authority": "RESEARCH_ONLY_NOT_MODEL_P_NOT_OFFICIAL",
    }


def brier_score(probability: float, outcome: int) -> float:
    p = float(probability)
    if not isfinite(p) or p < 0.0 or p > 1.0:
        raise PropPriorResearchError("probability must be in [0, 1]")
    if int(outcome) not in (0, 1) or outcome != int(outcome):
        raise PropPriorResearchError("outcome must be binary 0/1")
    return (p - int(outcome)) ** 2


def evaluate_heldout_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    noninferiority_margin: float = 0.0,
    tail_cutoff: float = 0.90,
) -> dict[str, Any]:
    """Compare frozen baseline vs candidate on strictly chronological rows.

    Each row needs ``target_at_utc``, ``prior_max_at_utc``, ``baseline_p``,
    ``candidate_p`` and binary ``outcome``.  Any row whose prior source is not
    strictly before target time fails closed instead of being silently skipped.
    """
    if not rows:
        raise PropPriorResearchError("held-out rows are required")
    if not isfinite(noninferiority_margin) or noninferiority_margin < 0.0:
        raise PropPriorResearchError("noninferiority_margin must be finite and non-negative")
    if not isfinite(tail_cutoff) or tail_cutoff <= 0.5 or tail_cutoff >= 1.0:
        raise PropPriorResearchError("tail_cutoff must be between 0.5 and 1")

    baseline_losses: list[float] = []
    candidate_losses: list[float] = []
    tail_baseline: list[float] = []
    tail_candidate: list[float] = []

    for index, row in enumerate(rows):
        target = _parse_utc(row.get("target_at_utc"))
        prior_max = _parse_utc(row.get("prior_max_at_utc"))
        if prior_max >= target:
            raise PropPriorResearchError(
                f"row {index} violates strict-prior chronology: prior_max_at_utc >= target_at_utc"
            )
        outcome = row.get("outcome")
        baseline_p = float(row.get("baseline_p"))
        candidate_p = float(row.get("candidate_p"))
        base_loss = brier_score(baseline_p, outcome)
        cand_loss = brier_score(candidate_p, outcome)
        baseline_losses.append(base_loss)
        candidate_losses.append(cand_loss)
        if (
            baseline_p >= tail_cutoff
            or baseline_p <= 1.0 - tail_cutoff
            or candidate_p >= tail_cutoff
            or candidate_p <= 1.0 - tail_cutoff
        ):
            tail_baseline.append(base_loss)
            tail_candidate.append(cand_loss)

    n = len(rows)
    baseline_brier = sum(baseline_losses) / n
    candidate_brier = sum(candidate_losses) / n
    tail_n = len(tail_baseline)
    tail_baseline_brier = sum(tail_baseline) / tail_n if tail_n else None
    tail_candidate_brier = sum(tail_candidate) / tail_n if tail_n else None
    noninferior = candidate_brier <= baseline_brier + float(noninferiority_margin)
    tail_nonworse = (
        True
        if tail_n == 0
        else tail_candidate_brier <= tail_baseline_brier + float(noninferiority_margin)
    )

    return {
        "n": n,
        "baseline_brier": baseline_brier,
        "candidate_brier": candidate_brier,
        "brier_delta_candidate_minus_baseline": candidate_brier - baseline_brier,
        "tail_n": tail_n,
        "tail_baseline_brier": tail_baseline_brier,
        "tail_candidate_brier": tail_candidate_brier,
        "noninferior": noninferior,
        "tail_nonworse": tail_nonworse,
        "passes_research_gate": bool(noninferior and tail_nonworse),
        "authority": "RESEARCH_ONLY_NOT_MODEL_P_NOT_OFFICIAL",
    }
