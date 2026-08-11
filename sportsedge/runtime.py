"""Deployment-aware SportsEdge runtime assembly."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, Mapping

from .deployments import load_registry
from .engine_registry import engine_registry
from .orchestrator import RunResult, run_slate


class RuntimeInputError(ValueError):
    pass


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeInputError("timestamp must be a non-empty ISO-8601 string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise RuntimeInputError(f"invalid ISO timestamp: {value}") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise RuntimeInputError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def runtime_deployments(path: str | Path = "config/deployments.json") -> dict[str, dict[str, Any]]:
    reg = load_registry(path)
    return {market: {"market": market, **meta} for market, meta in reg["markets"].items()}


def _normalize_candidates(candidates: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, Mapping):
            normalized.append({"model_input": None, "quote": None})
            continue
        model_input = item.get("model_input")
        quote = item.get("quote")
        if isinstance(quote, Mapping):
            quote = dict(quote)
            if "retrieved_at" in quote and isinstance(quote["retrieved_at"], str):
                quote["retrieved_at"] = parse_timestamp(quote["retrieved_at"])
        normalized.append({"model_input": model_input, "quote": quote})
    return normalized


def run_payload(payload: Mapping[str, Any], *, registry_path: str | Path = "config/deployments.json") -> list[RunResult]:
    if not isinstance(payload, Mapping):
        raise RuntimeInputError("payload must be an object")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list):
        raise RuntimeInputError("payload.candidates must be a list")
    ingestion_now = parse_timestamp(payload.get("ingestion_now"))
    finalization_now = parse_timestamp(payload.get("finalization_now"))
    if finalization_now < ingestion_now:
        raise RuntimeInputError("finalization_now cannot precede ingestion_now")

    min_edge = payload.get("min_edge", 0.0)
    kelly_multiplier = payload.get("kelly_multiplier", 0.25)
    if isinstance(min_edge, bool) or isinstance(kelly_multiplier, bool):
        raise RuntimeInputError("min_edge/kelly_multiplier must be numeric")
    try:
        min_edge = float(min_edge)
        kelly_multiplier = float(kelly_multiplier)
    except (TypeError, ValueError) as exc:
        raise RuntimeInputError("min_edge/kelly_multiplier must be numeric") from exc
    if not isfinite(min_edge) or min_edge < 0:
        raise RuntimeInputError("min_edge must be finite and >= 0")
    if not isfinite(kelly_multiplier) or not 0 <= kelly_multiplier <= 1:
        raise RuntimeInputError("kelly_multiplier must be finite and in [0,1]")

    return run_slate(
        _normalize_candidates(candidates),
        engines=engine_registry(),
        deployments=runtime_deployments(registry_path),
        ingestion_now=ingestion_now,
        finalization_now=finalization_now,
        min_edge=min_edge,
        kelly_multiplier=kelly_multiplier,
    )


def result_to_dict(result: RunResult) -> dict[str, Any]:
    out = {
        "market": result.market,
        "model_p": result.model_p,
        "bet_status": result.bet_status,
        "reason": result.reason,
    }
    if result.decision is not None:
        out["decision"] = {
            "model_status": result.decision.model_status,
            "bet_status": result.decision.bet_status,
            "implied_probability": result.decision.implied_probability,
            "edge": result.decision.edge,
            "ev_per_dollar": result.decision.ev_per_dollar,
            "kelly_fraction": result.decision.kelly_fraction,
        }
    else:
        out["decision"] = None
    return out
