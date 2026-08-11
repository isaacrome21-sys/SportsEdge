"""Canonical runtime engine adapters.

Adapters are deliberately thin: they translate the external canonical market
contract into a validated market engine's frozen input contract, then translate
its probability output back into the common orchestrator schema. They never
read sportsbook prices or infer missing candidate identity.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Mapping

from .hits_engine import simulate_hits


class EngineDispatchError(ValueError):
    pass


_HITS_LINES = (0.5, 1.5, 2.5)


def _finite_line(value: Any) -> float:
    if isinstance(value, bool):
        raise EngineDispatchError("line must be numeric, not boolean")
    try:
        line = float(value)
    except (TypeError, ValueError) as exc:
        raise EngineDispatchError("line must be numeric") from exc
    if not isfinite(line):
        raise EngineDispatchError("line must be finite")
    return line


def hits_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    """Return common-schema Model_P for a canonical HITS candidate."""
    if model_input.get("market") != "HITS":
        raise EngineDispatchError("Hits adapter requires market=HITS")
    line = _finite_line(model_input.get("line"))
    if line not in _HITS_LINES:
        raise EngineDispatchError(f"unsupported HITS line {line}; allowed={_HITS_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("HITS side must be OVER or UNDER")

    # The validated engine's historical contract uses lowercase 'hits'. Keep
    # that implementation frozen and translate only at this explicit seam.
    internal = dict(model_input)
    internal["market"] = "hits"
    result = simulate_hits(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    model_p = p_over if side == "OVER" else 1.0 - p_over

    return {
        "game_id": model_input.get("game_id"),
        "market": "HITS",
        "entity_id": model_input.get("entity_id"),
        "line": model_input.get("line"),
        "side": side,
        "model_p": model_p,
        "model_input_hash": result.model_input_hash,
        "engine_version": result.engine_version,
        "seed_policy": result.seed_policy,
        "mc_paths": result.mc_paths,
    }


def engine_registry() -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    """Only engines with an actual checked-in production implementation live here."""
    return {
        "HITS": hits_engine_adapter,
    }
