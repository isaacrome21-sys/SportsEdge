"""Finite-sample shrinkage for empirical MLB settlement probabilities.

This module treats strictly-prior empirical outcome mass as evidence, not certainty.
It applies a Jeffreys Dirichlet prior (0.5 per settlement category) and reports a
posterior predictive probability plus marginal posterior uncertainty. Sportsbook
prices are never inputs.
"""
from __future__ import annotations

from math import isfinite, sqrt
from typing import Any, Sequence

JEFFREYS_ALPHA = 0.5
PRIOR_NAME = "JEFFREYS_SETTLEMENT_DIRICHLET_0_5"


class EmpiricalBayesError(ValueError):
    pass


def effective_sample_size(weights: Sequence[float] | None, n: int) -> float:
    if n <= 0:
        raise EmpiricalBayesError("sample size must be positive")
    if weights is None:
        return float(n)
    if len(weights) != n:
        raise EmpiricalBayesError("weights must align one-to-one with observations")
    vals = [float(w) for w in weights]
    if any((not isfinite(w)) or w <= 0 for w in vals):
        raise EmpiricalBayesError("weights must be finite and positive")
    total = sum(vals)
    normalized = [w / total for w in vals]
    return 1.0 / sum(w * w for w in normalized)


def posterior_settlement_mass(*, over_mass: float, under_mass: float, push_mass: float,
                              effective_n: float, has_push: bool) -> dict[str, Any]:
    masses = [float(over_mass), float(under_mass), float(push_mass)]
    if any((not isfinite(x)) or x < 0 or x > 1 for x in masses):
        raise EmpiricalBayesError("settlement masses must be finite probabilities")
    if abs(sum(masses) - 1.0) > 1e-9:
        raise EmpiricalBayesError("settlement mass does not conserve")
    if not has_push and abs(push_mass) > 1e-12:
        raise EmpiricalBayesError("non-integer line cannot carry push mass")
    if not isfinite(effective_n) or effective_n <= 0:
        raise EmpiricalBayesError("effective sample size must be positive")

    active = ("over", "under", "push") if has_push else ("over", "under")
    raw = {"over": over_mass, "under": under_mass, "push": push_mass}
    alpha = {name: JEFFREYS_ALPHA + effective_n * raw[name] for name in active}
    total_alpha = sum(alpha.values())
    posterior = {name: alpha[name] / total_alpha for name in active}
    sd = {
        name: sqrt(alpha[name] * (total_alpha - alpha[name]) /
                   (total_alpha * total_alpha * (total_alpha + 1.0)))
        for name in active
    }
    if not has_push:
        posterior["push"] = 0.0
        sd["push"] = 0.0
    return {
        "p_over": posterior["over"],
        "p_under": posterior["under"],
        "p_push": posterior["push"],
        "raw_over": over_mass,
        "raw_under": under_mass,
        "raw_push": push_mass,
        "effective_sample_size": float(effective_n),
        "posterior_sd_over": sd["over"],
        "posterior_sd_under": sd["under"],
        "posterior_sd_push": sd["push"],
        "prior": PRIOR_NAME,
    }
