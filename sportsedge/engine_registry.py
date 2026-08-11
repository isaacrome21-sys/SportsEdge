"""Canonical runtime engine adapters.

Adapters translate the external canonical market contract into each validated
engine's frozen input contract, then back to the common orchestrator schema.
They never read sportsbook prices or infer missing candidate identity.
"""
from __future__ import annotations

from math import isfinite
from typing import Any, Callable, Mapping

from .bb_engine import simulate_bb
from .hits_engine import simulate_hits
from .total_bases_engine import simulate_total_bases


class EngineDispatchError(ValueError):
    pass


_HITTER_LINES = (0.5, 1.5, 2.5)
_BB_LINES = (0.5, 1.5, 2.5, 3.5)


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


def _common_output(model_input: Mapping[str, Any], result, model_p: float, market: str) -> dict[str, Any]:
    return {
        "game_id": model_input.get("game_id"),
        "market": market,
        "entity_id": model_input.get("entity_id"),
        "line": model_input.get("line"),
        "side": model_input.get("side"),
        "model_p": float(model_p),
        "model_input_hash": result.model_input_hash,
        "engine_version": result.engine_version,
        "seed_policy": result.seed_policy,
        "mc_paths": result.mc_paths,
    }


def hits_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "HITS":
        raise EngineDispatchError("Hits adapter requires market=HITS")
    line = _finite_line(model_input.get("line"))
    if line not in _HITTER_LINES:
        raise EngineDispatchError(f"unsupported HITS line {line}; allowed={_HITTER_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("HITS side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "hits"
    result = simulate_hits(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "HITS")


def total_bases_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "TOTAL_BASES":
        raise EngineDispatchError("Total Bases adapter requires market=TOTAL_BASES")
    line = _finite_line(model_input.get("line"))
    if line not in _HITTER_LINES:
        raise EngineDispatchError(f"unsupported TOTAL_BASES line {line}; allowed={_HITTER_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("TOTAL_BASES side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "total_bases"
    result = simulate_total_bases(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "TOTAL_BASES")


def pitcher_bb_engine_adapter(model_input: Mapping[str, Any]) -> dict[str, Any]:
    if model_input.get("market") != "PITCHER_BB":
        raise EngineDispatchError("Pitcher BB adapter requires market=PITCHER_BB")
    line = _finite_line(model_input.get("line"))
    if line not in _BB_LINES:
        raise EngineDispatchError(f"unsupported PITCHER_BB line {line}; allowed={_BB_LINES}")
    side = model_input.get("side")
    if side not in ("OVER", "UNDER"):
        raise EngineDispatchError("PITCHER_BB side must be OVER or UNDER")
    internal = dict(model_input); internal["market"] = "pitcher_walks"
    result = simulate_bb(internal, thresholds=(line,))
    p_over = float(result.probs[line])
    return _common_output(model_input, result, p_over if side == "OVER" else 1.0 - p_over, "PITCHER_BB")


def engine_registry() -> dict[str, Callable[[Mapping[str, Any]], Mapping[str, Any]]]:
    return {
        "HITS": hits_engine_adapter,
        "TOTAL_BASES": total_bases_engine_adapter,
        "PITCHER_BB": pitcher_bb_engine_adapter,
    }
