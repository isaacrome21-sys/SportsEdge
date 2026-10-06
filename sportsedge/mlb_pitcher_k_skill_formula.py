"""Research-only frozen formula for the MLB pitcher-K Statcast skill candidate.

No coefficients are supplied by default.  A development-only frozen fit artifact is
required before this module can emit a research probability.  Outputs from this
module are never Model_P or bettor-facing authority.
"""
from __future__ import annotations

from math import exp, floor, isfinite, log
from typing import Any, Mapping, Sequence

INPUT_SCHEMA = "MLB_PITCHER_K_SKILL_BOUND_CANDIDATE_V1"
FIT_SCHEMA = "MLB_PITCHER_K_SKILL_FIT_V1"
FORMULA_ID = "MLB_PITCHER_K_SKILL_POISSON_V1"
AUTHORITY = "RESEARCH_ONLY_NOT_MODEL_INPUT_NOT_DEPLOYED"


class PitcherKSkillFormulaError(ValueError):
    pass


def _positive(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherKSkillFormulaError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherKSkillFormulaError(f"{name} must be numeric") from exc
    if not isfinite(out) or out <= 0:
        raise PitcherKSkillFormulaError(f"{name} must be positive")
    return out


def _rate(value: Any, name: str) -> float:
    out = _positive(value, name)
    if out > 1:
        raise PitcherKSkillFormulaError(f"{name} outside (0,1]")
    return out


def _geomean(values: Sequence[Any], name: str) -> float:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence) or not values:
        raise PitcherKSkillFormulaError(f"{name} must be a nonempty sequence")
    xs = [_positive(v, f"{name}[{i}]") for i, v in enumerate(values)]
    return exp(sum(log(v) for v in xs) / len(xs))


def formula_features(candidate: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(candidate, Mapping) or candidate.get("schema") != INPUT_SCHEMA:
        raise PitcherKSkillFormulaError("unexpected skill-bound candidate schema")
    if candidate.get("authority") != AUTHORITY:
        raise PitcherKSkillFormulaError("candidate authority must remain research only")
    if candidate.get("deployment") is not False or candidate.get("model_p_eligible") is not False:
        raise PitcherKSkillFormulaError("deployed/model-eligible candidate forbidden")
    if candidate.get("source_complete") is not True or candidate.get("missing_components"):
        raise PitcherKSkillFormulaError("source-complete candidate required")

    components = candidate.get("components")
    if not isinstance(components, Mapping):
        raise PitcherKSkillFormulaError("candidate components required")
    workload = (components.get("workload_leash") or {}).get("summary") or {}
    opponent = components.get("opponent_k") or {}
    lineup = components.get("lineup_k")
    skill = components.get("pitcher_skill") or {}

    mean_bf = _positive(workload.get("recent_mean_batters_faced"), "recent_mean_batters_faced")
    k_per_bf = _rate(workload.get("recent_mean_k_per_batter_faced"), "recent_mean_k_per_batter_faced")
    target_rel = _positive(opponent.get("target_rel"), "opponent.target_rel")
    history_rel = opponent.get("history_rel")
    if abs(_positive(opponent.get("beta"), "opponent.beta") - 1.0) > 1e-12:
        raise PitcherKSkillFormulaError("opponent beta must remain frozen at 1.0")
    opponent_factor = target_rel / _geomean(history_rel, "opponent.history_rel")

    lineup_factor = 1.0
    if lineup is not None:
        if not isinstance(lineup, Mapping):
            raise PitcherKSkillFormulaError("lineup component must be an object")
        if abs(_positive(lineup.get("gamma"), "lineup.gamma") - 0.5) > 1e-12:
            raise PitcherKSkillFormulaError("lineup gamma must remain frozen at 0.5")
        target_dev = _positive(lineup.get("target_deviation"), "lineup.target_deviation")
        lineup_factor = (target_dev / _geomean(lineup.get("history_deviation"), "lineup.history_deviation")) ** 0.5

    hand = str(skill.get("pitcher_hand") or "").upper()
    if hand not in {"L", "R"}:
        raise PitcherKSkillFormulaError("pitcher hand required for calibration slicing")
    return {
        "base_lambda": mean_bf * k_per_bf * opponent_factor * lineup_factor,
        "recent_mean_batters_faced": mean_bf,
        "recent_mean_k_per_batter_faced": k_per_bf,
        "opponent_factor": opponent_factor,
        "lineup_factor": lineup_factor,
        "whiff_rate": _rate(skill.get("whiff_rate"), "whiff_rate"),
        "chase_rate": _rate(skill.get("chase_rate"), "chase_rate"),
        "pitcher_hand": hand,
    }


def _fit_parameters(fit: Mapping[str, Any]) -> dict[str, float]:
    if not isinstance(fit, Mapping) or fit.get("schema") != FIT_SCHEMA:
        raise PitcherKSkillFormulaError("frozen development fit artifact required")
    if fit.get("formula_id") != FORMULA_ID:
        raise PitcherKSkillFormulaError("fit/formula identity mismatch")
    if fit.get("status") != "FROZEN_DEVELOPMENT_FIT":
        raise PitcherKSkillFormulaError("development fit is not frozen")
    if fit.get("training_only") is not True or fit.get("forward_evaluation_rows_seen") is not False:
        raise PitcherKSkillFormulaError("fit artifact must predate forward evaluation")
    out = {}
    for name in ("intercept", "beta_whiff", "beta_chase", "whiff_mean", "whiff_std", "chase_mean", "chase_std"):
        try:
            value = float(fit[name])
        except (KeyError, TypeError, ValueError) as exc:
            raise PitcherKSkillFormulaError(f"fit parameter missing/invalid: {name}") from exc
        if not isfinite(value):
            raise PitcherKSkillFormulaError(f"fit parameter nonfinite: {name}")
        out[name] = value
    if out["whiff_std"] <= 0 or out["chase_std"] <= 0:
        raise PitcherKSkillFormulaError("development standard deviations must be positive")
    return out


def research_probability_over(candidate: Mapping[str, Any], *, fit: Mapping[str, Any], line: float) -> dict[str, Any]:
    x = float(line)
    if not isfinite(x) or abs((x - floor(x)) - 0.5) > 1e-12 or not 0.5 <= x <= 19.5:
        raise PitcherKSkillFormulaError("candidate supports frozen K half-lines 0.5..19.5 only")
    f = formula_features(candidate)
    p = _fit_parameters(fit)
    zw = (f["whiff_rate"] - p["whiff_mean"]) / p["whiff_std"]
    zc = (f["chase_rate"] - p["chase_mean"]) / p["chase_std"]
    lam = f["base_lambda"] * exp(p["intercept"] + p["beta_whiff"] * zw + p["beta_chase"] * zc)
    if not isfinite(lam) or lam <= 0 or lam > 20:
        raise PitcherKSkillFormulaError("candidate lambda outside frozen safe range (0,20]")

    kmax = floor(x)
    term = exp(-lam)
    cdf = term
    for k in range(1, kmax + 1):
        term *= lam / k
        cdf += term
    p_over = min(1.0, max(0.0, 1.0 - cdf))
    return {
        "schema": "MLB_PITCHER_K_SKILL_RESEARCH_PROBABILITY_V1",
        "formula_id": FORMULA_ID,
        "market": "PITCHER_K",
        "line": x,
        "research_p_over": p_over,
        "lambda": lam,
        "features": f,
        "authority": AUTHORITY,
        "model_p_eligible": False,
        "deployment": False,
    }
