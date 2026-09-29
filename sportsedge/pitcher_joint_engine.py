"""Predictive pitcher prop challenger from strictly-prior joint start rows.

The engine keeps each historical start as one coherent row, but no longer treats a
small empirical pool as the complete future support. A deterministic discrete
kernel turns each marginal into a proper predictive PMF, while optional strictly-
prior recency weights and context target means can shift the distribution without
using sportsbook prices.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_count_kernel import CountKernelError, discrete_kernel_pmf, normalize_weights, price_from_pmf

ENGINE_VERSION = "mlb_pitcher_joint_empirical_kernel_v3"
PITCHER_MARKETS = frozenset({
    "PITCHER_K", "PITCHER_OUTS", "PITCHER_ER", "PITCHER_HITS_ALLOWED", "PITCHER_BB",
    "PITCHER_HITS_WALKS_ER", "EITHER_PITCHER_HITS_ALLOWED", "EITHER_PITCHER_BB",
    "EITHER_PITCHER_ER",
})


class PitcherJointEngineError(ValueError):
    pass


def _f(v: Any, name: str, lo: float = 0.0) -> float:
    if isinstance(v, bool):
        raise PitcherJointEngineError(f"{name} must be numeric")
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise PitcherJointEngineError(f"{name} must be numeric") from exc
    if not isfinite(x) or x < lo:
        raise PitcherJointEngineError(f"{name} invalid")
    return x


def _sha(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalize_pool(raw: Any, name: str) -> list[dict[str, Any]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise PitcherJointEngineError(f"{name} must be a sequence")
    rows: list[dict[str, Any]] = []
    required = ("strikeouts", "outs", "earned_runs", "hits_allowed", "walks_allowed")
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise PitcherJointEngineError(f"{name}[{i}] must be object")
        row: dict[str, Any] = {}
        for key in required:
            x = _f(item.get(key), f"{name}[{i}].{key}")
            if int(x) != x:
                raise PitcherJointEngineError(f"{name}[{i}].{key} must be integer")
            row[key] = int(x)
        if not 0 <= row["outs"] <= 27:
            raise PitcherJointEngineError(f"{name}[{i}].outs outside [0,27]")
        if "_weight" in item:
            row["_weight"] = _f(item.get("_weight"), f"{name}[{i}]._weight")
            if row["_weight"] <= 0:
                raise PitcherJointEngineError(f"{name}[{i}]._weight must be positive")
        rows.append(row)
    if len(rows) < 5:
        raise PitcherJointEngineError(f"{name} requires at least 5 prior starts")
    return rows


def _value(row: Mapping[str, Any], market: str) -> int:
    if market == "PITCHER_K":
        return int(row["strikeouts"])
    if market == "PITCHER_OUTS":
        return int(row["outs"])
    if market == "PITCHER_ER":
        return int(row["earned_runs"])
    if market == "PITCHER_HITS_ALLOWED":
        return int(row["hits_allowed"])
    if market == "PITCHER_BB":
        return int(row["walks_allowed"])
    if market == "PITCHER_HITS_WALKS_ER":
        return int(row["hits_allowed"]) + int(row["walks_allowed"]) + int(row["earned_runs"])
    raise PitcherJointEngineError(f"unsupported single-pitcher market {market}")


def _pool_weights(pool: Sequence[Mapping[str, Any]], explicit: Any = None) -> list[float]:
    try:
        if explicit is not None:
            return normalize_weights(explicit, len(pool))
        embedded = [row.get("_weight") for row in pool]
        if all(value is not None for value in embedded):
            return normalize_weights([float(value) for value in embedded], len(pool))
        return normalize_weights(None, len(pool))
    except CountKernelError as exc:
        raise PitcherJointEngineError(str(exc)) from exc


def _raw_price(values: Sequence[int], weights: Sequence[float], line: float, side: str) -> tuple[float, float]:
    p_over = sum(w for v, w in zip(values, weights) if v > line)
    p_under = sum(w for v, w in zip(values, weights) if v < line)
    p_push = sum(w for v, w in zip(values, weights) if v == line) if float(line).is_integer() else 0.0
    return (p_over if side == "OVER" else p_under), p_push


def _target_for(features: Mapping[str, Any], market: str) -> float | None:
    raw = features.get("target_means")
    if not isinstance(raw, Mapping):
        return None
    aliases = {
        "PITCHER_K": ("PITCHER_K", "strikeouts"),
        "PITCHER_OUTS": ("PITCHER_OUTS", "outs"),
        "PITCHER_ER": ("PITCHER_ER", "earned_runs"),
        "PITCHER_HITS_ALLOWED": ("PITCHER_HITS_ALLOWED", "hits_allowed"),
        "PITCHER_BB": ("PITCHER_BB", "walks_allowed"),
        "PITCHER_HITS_WALKS_ER": ("PITCHER_HITS_WALKS_ER", "hits_walks_er"),
    }
    for key in aliases.get(market, (market,)):
        if key in raw:
            return _f(raw[key], f"target_means.{key}")
    return None


def _price_pool(
    pool: Sequence[Mapping[str, Any]],
    *,
    market: str,
    line: float,
    side: str,
    explicit_weights: Any = None,
    target_mean: float | None = None,
) -> tuple[float, float, float, float, dict[str, float]]:
    values = [_value(row, market) for row in pool]
    weights = _pool_weights(pool, explicit_weights)
    upper = 27 if market == "PITCHER_OUTS" else None
    try:
        pmf, meta = discrete_kernel_pmf(
            values, weights=weights, lower=0, upper=upper, target_mean=target_mean
        )
        model_p, push_p = price_from_pmf(pmf, line=line, side=side)
    except CountKernelError as exc:
        raise PitcherJointEngineError(str(exc)) from exc
    raw_p, raw_push = _raw_price(values, weights, line, side)
    return model_p, push_p, raw_p, raw_push, meta


def price_pitcher_market(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market", "")).upper()
    if market not in PITCHER_MARKETS:
        raise PitcherJointEngineError(f"unsupported pitcher market {market}")
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise PitcherJointEngineError("side must be OVER or UNDER")
    line = _f(model_input.get("line"), "line")
    features = model_input.get("features")
    if not isinstance(features, Mapping):
        raise PitcherJointEngineError("features required")

    if market.startswith("EITHER_PITCHER_"):
        pool_a = _normalize_pool(features.get("pitcher_a_history"), "pitcher_a_history")
        pool_b = _normalize_pool(features.get("pitcher_b_history"), "pitcher_b_history")
        base = {
            "EITHER_PITCHER_HITS_ALLOWED": "PITCHER_HITS_ALLOWED",
            "EITHER_PITCHER_BB": "PITCHER_BB",
            "EITHER_PITCHER_ER": "PITCHER_ER",
        }[market]
        pa, ppa, raw_a, raw_push_a, meta_a = _price_pool(
            pool_a, market=base, line=line, side=side,
            explicit_weights=features.get("pitcher_a_weights"), target_mean=None,
        )
        pb, ppb, raw_b, raw_push_b, meta_b = _price_pool(
            pool_b, market=base, line=line, side=side,
            explicit_weights=features.get("pitcher_b_weights"), target_mean=None,
        )
        opposite_a = max(0.0, 1.0 - pa - ppa)
        opposite_b = max(0.0, 1.0 - pb - ppb)
        p = 1.0 - (1.0 - pa) * (1.0 - pb)
        p_push = ((ppa + opposite_a) * (ppb + opposite_b)) - (opposite_a * opposite_b)

        raw_opp_a = max(0.0, 1.0 - raw_a - raw_push_a)
        raw_opp_b = max(0.0, 1.0 - raw_b - raw_push_b)
        raw_p = 1.0 - (1.0 - raw_a) * (1.0 - raw_b)
        raw_push = ((raw_push_a + raw_opp_a) * (raw_push_b + raw_opp_b)) - (raw_opp_a * raw_opp_b)
        identity_features = {"pitcher_a_history": pool_a, "pitcher_b_history": pool_b}
        predictive_meta: dict[str, Any] = {"pitcher_a": meta_a, "pitcher_b": meta_b}
    else:
        pool = _normalize_pool(features.get("history_pool"), "history_pool")
        target_mean = _target_for(features, market)
        p, p_push, raw_p, raw_push, predictive_meta = _price_pool(
            pool, market=market, line=line, side=side,
            explicit_weights=features.get("history_weights"), target_mean=target_mean,
        )
        identity_features = {
            "history_pool": pool,
            "history_weights": features.get("history_weights"),
            "target_means": features.get("target_means"),
        }

    digest = _sha({
        "engine": ENGINE_VERSION,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "feature_source_hash": model_input.get("feature_source_hash"),
        "features": identity_features,
    })
    return {
        "game_id": model_input.get("game_id"),
        "market": market,
        "entity_id": model_input.get("entity_id"),
        "line": line,
        "side": side,
        "model_p": float(p),
        "push_p": float(p_push),
        "raw_empirical_p": float(raw_p),
        "raw_empirical_push_p": float(raw_push),
        "model_input_hash": digest,
        "engine_version": ENGINE_VERSION,
        "seed_policy": "analytic_discrete_kernel_strict_prior_joint_rows",
        "mc_paths": 0,
        "meta": {
            "predictive_smoothing": "gaussian_discrete_kernel",
            "predictive": predictive_meta,
        },
    }
