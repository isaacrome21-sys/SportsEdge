"""Bounded empirical pitcher-outs challenger.

This candidate prices pitcher outs from a strictly-prior workload pool rather
than an unbounded count distribution. It is intentionally analytic and
shadow-only until line-level behavioral validation is complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Iterable

from .source_lineage import canonical_json_sha256

ENGINE_VERSION = "pitcher_outs_empirical_workload_v1_candidate"
MIN_STARTS = 5
MAX_OUTS = 27


class PitcherOutsEngineError(ValueError):
    pass


@dataclass(frozen=True)
class PitcherOutsOutput:
    engine_version: str
    model_input_hash: str
    seed_policy: str
    sample_size: int
    line: float
    side: str
    model_p: float
    push_p: float


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise PitcherOutsEngineError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherOutsEngineError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise PitcherOutsEngineError(f"{name} must be finite")
    return out


def _clean_pool(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise PitcherOutsEngineError("workload_pool must be a list/tuple")
    if len(value) < MIN_STARTS:
        raise PitcherOutsEngineError(f"workload_pool requires at least {MIN_STARTS} prior starts")
    cleaned: list[int] = []
    for raw in value:
        if isinstance(raw, bool):
            raise PitcherOutsEngineError("workload_pool values must be integers")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise PitcherOutsEngineError("workload_pool values must be integers") from exc
        if not isfinite(numeric) or numeric != int(numeric):
            raise PitcherOutsEngineError("workload_pool values must be integers")
        outs = int(numeric)
        if not 0 <= outs <= MAX_OUTS:
            raise PitcherOutsEngineError("workload_pool violates physical support [0,27]")
        cleaned.append(outs)
    return tuple(cleaned)


def price_pitcher_outs(model_input: dict[str, Any]) -> PitcherOutsOutput:
    if not isinstance(model_input, dict):
        raise PitcherOutsEngineError("model_input must be a dict")
    if model_input.get("market") not in {"PITCHER_OUTS", "pitcher_outs"}:
        raise PitcherOutsEngineError("wrong market for pitcher-outs engine")
    features = model_input.get("features")
    if not isinstance(features, dict) or set(features) != {"workload_pool"}:
        raise PitcherOutsEngineError("features must contain exactly workload_pool")

    pool = _clean_pool(features["workload_pool"])
    line = _finite(model_input.get("line"), "line")
    if line < 0 or line > MAX_OUTS:
        raise PitcherOutsEngineError("line outside physical support [0,27]")
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise PitcherOutsEngineError("side must be OVER or UNDER")

    n = len(pool)
    p_over = sum(1 for outs in pool if outs > line) / n
    p_under = sum(1 for outs in pool if outs < line) / n
    p_push = sum(1 for outs in pool if outs == line) / n
    if abs((p_over + p_under + p_push) - 1.0) > 1e-12:
        raise PitcherOutsEngineError("probability mass does not conserve")
    model_p = p_over if side == "OVER" else p_under

    digest = canonical_json_sha256({
        "engine": ENGINE_VERSION,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "workload_pool": list(pool),
        "feature_source_hash": model_input.get("feature_source_hash"),
    })
    return PitcherOutsOutput(
        engine_version=ENGINE_VERSION,
        model_input_hash=digest,
        seed_policy="analytic_empirical_workload",
        sample_size=n,
        line=line,
        side=side,
        model_p=float(model_p),
        push_p=float(p_push),
    )
