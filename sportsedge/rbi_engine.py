"""Empirical batter-RBI shape challenger.

RBI is not a one-event-per-PA count, so it is intentionally not routed through
the PA-bounded binomial family. This candidate prices from a strictly-prior
game-level RBI distribution to isolate the incumbent Poisson shape error. It is
shadow-only until behavioral validation is complete.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .source_lineage import canonical_json_sha256

ENGINE_VERSION = "rbi_empirical_game_v1_candidate"
MIN_GAMES = 10


class RBIEngineError(ValueError):
    pass


@dataclass(frozen=True)
class RBIOutput:
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
        raise RBIEngineError(f"{name} must be numeric")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise RBIEngineError(f"{name} must be numeric") from exc
    if not isfinite(out):
        raise RBIEngineError(f"{name} must be finite")
    return out


def _clean_pool(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise RBIEngineError("rbi_pool must be a list/tuple")
    if len(value) < MIN_GAMES:
        raise RBIEngineError(f"rbi_pool requires at least {MIN_GAMES} prior games")
    cleaned: list[int] = []
    for raw in value:
        if isinstance(raw, bool):
            raise RBIEngineError("rbi_pool values must be integers")
        try:
            numeric = float(raw)
        except (TypeError, ValueError) as exc:
            raise RBIEngineError("rbi_pool values must be integers") from exc
        if not isfinite(numeric) or numeric != int(numeric) or numeric < 0:
            raise RBIEngineError("rbi_pool values must be non-negative integers")
        cleaned.append(int(numeric))
    return tuple(cleaned)


def price_rbi(model_input: dict[str, Any]) -> RBIOutput:
    if not isinstance(model_input, dict):
        raise RBIEngineError("model_input must be a dict")
    if model_input.get("market") not in {"RBI", "rbi"}:
        raise RBIEngineError("wrong market for RBI engine")
    features = model_input.get("features")
    if not isinstance(features, dict) or set(features) != {"rbi_pool"}:
        raise RBIEngineError("features must contain exactly rbi_pool")

    pool = _clean_pool(features["rbi_pool"])
    line = _finite(model_input.get("line"), "line")
    if line < 0:
        raise RBIEngineError("line must be non-negative")
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise RBIEngineError("side must be OVER or UNDER")

    n = len(pool)
    p_over = sum(1 for rbi in pool if rbi > line) / n
    p_under = sum(1 for rbi in pool if rbi < line) / n
    p_push = sum(1 for rbi in pool if rbi == line) / n
    if abs((p_over + p_under + p_push) - 1.0) > 1e-12:
        raise RBIEngineError("probability mass does not conserve")
    model_p = p_over if side == "OVER" else p_under

    digest = canonical_json_sha256({
        "engine": ENGINE_VERSION,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "rbi_pool": list(pool),
        "feature_source_hash": model_input.get("feature_source_hash"),
    })
    return RBIOutput(
        engine_version=ENGINE_VERSION,
        model_input_hash=digest,
        seed_policy="analytic_empirical_game_distribution",
        sample_size=n,
        line=line,
        side=side,
        model_p=float(model_p),
        push_p=float(p_push),
    )
