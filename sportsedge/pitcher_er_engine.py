"""Empirical pitcher-earned-runs challenger.

Prices PITCHER_ER from a strictly-prior start-level earned-run pool. This is a
shape challenger only: it intentionally does not add opponent/park/context
parameters, so behavioral comparison isolates the incumbent Poisson form error.
It remains shadow-only until line-level validation is complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .source_lineage import canonical_json_sha256

ENGINE_VERSION = "pitcher_er_empirical_start_v1_candidate"
MIN_STARTS = 5


class PitcherEREngineError(ValueError):
    pass


@dataclass(frozen=True)
class PitcherEROutput:
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
        raise PitcherEREngineError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise PitcherEREngineError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise PitcherEREngineError(f"{name} must be finite")
    return out


def _clean_pool(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise PitcherEREngineError("earned_runs_pool must be a list/tuple")
    if len(value) < MIN_STARTS:
        raise PitcherEREngineError(f"earned_runs_pool requires at least {MIN_STARTS} prior starts")
    cleaned: list[int] = []
    for raw in value:
        if isinstance(raw, bool):
            raise PitcherEREngineError("earned_runs_pool values must be integers")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise PitcherEREngineError("earned_runs_pool values must be integers") from exc
        if not isfinite(numeric) or numeric != int(numeric) or numeric < 0:
            raise PitcherEREngineError("earned_runs_pool values must be non-negative integers")
        cleaned.append(int(numeric))
    return tuple(cleaned)


def price_pitcher_er(model_input: dict[str, Any]) -> PitcherEROutput:
    if not isinstance(model_input, dict):
        raise PitcherEREngineError("model_input must be a dict")
    if model_input.get("market") not in {"PITCHER_ER", "pitcher_er"}:
        raise PitcherEREngineError("wrong market for pitcher-ER engine")
    features = model_input.get("features")
    if not isinstance(features, dict) or set(features) != {"earned_runs_pool"}:
        raise PitcherEREngineError("features must contain exactly earned_runs_pool")

    pool = _clean_pool(features["earned_runs_pool"])
    line = _finite(model_input.get("line"), "line")
    if line < 0:
        raise PitcherEREngineError("line must be non-negative")
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise PitcherEREngineError("side must be OVER or UNDER")

    n = len(pool)
    p_over = sum(1 for er in pool if er > line) / n
    p_under = sum(1 for er in pool if er < line) / n
    p_push = sum(1 for er in pool if er == line) / n
    if abs((p_over + p_under + p_push) - 1.0) > 1e-12:
        raise PitcherEREngineError("probability mass does not conserve")
    model_p = p_over if side == "OVER" else p_under

    digest = canonical_json_sha256({
        "engine": ENGINE_VERSION,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "earned_runs_pool": list(pool),
        "feature_source_hash": model_input.get("feature_source_hash"),
    })
    return PitcherEROutput(
        engine_version=ENGINE_VERSION,
        model_input_hash=digest,
        seed_policy="analytic_empirical_start_distribution",
        sample_size=n,
        line=line,
        side=side,
        model_p=float(model_p),
        push_p=float(p_push),
    )
