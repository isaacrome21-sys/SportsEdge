"""Coherent hitter prop challenger from strictly-prior game rows.

Every prior game is one joint state containing PA, hits, HR, total bases, RBI,
runs, stolen bases, walks and extra-base hits. All individual and combination
markets are marginals of the same rows, so overlapping propositions cannot
contradict one another. This is the honest v1 until PA-level play-by-play state
is available; it does not pretend game logs identify within-PA RBI/run structure.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "mlb_hitter_joint_empirical_v1"

HITTER_MARKETS = frozenset({
    "HITS", "HOME_RUNS", "TOTAL_BASES", "RBI", "RUNS", "STOLEN_BASES", "BATTER_BB",
    "EXTRA_BASE_HITS", "HITS_RUNS_RBIS", "HITS_RUNS_STOLEN_BASES", "RUNS_RBIS",
    "HITS_STOLEN_BASES", "HITS_WALKS_STOLEN_BASES",
})

class HitterJointEngineError(ValueError):
    pass


def _f(v: Any, name: str, lo: float = 0.0) -> float:
    if isinstance(v, bool):
        raise HitterJointEngineError(f"{name} must be numeric")
    try:
        x = float(v)
    except (TypeError, ValueError) as exc:
        raise HitterJointEngineError(f"{name} must be numeric") from exc
    if not isfinite(x) or x < lo:
        raise HitterJointEngineError(f"{name} invalid")
    return x


def _sha(v: Any) -> str:
    raw = json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _normalize_pool(raw: Any) -> list[dict[str, int]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise HitterJointEngineError("history_pool must be a sequence")
    required = (
        "plate_appearances", "hits", "home_runs", "total_bases", "rbi",
        "runs", "stolen_bases", "walks", "extra_base_hits",
    )
    rows: list[dict[str, int]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise HitterJointEngineError(f"history_pool[{i}] must be object")
        row: dict[str, int] = {}
        for key in required:
            x = _f(item.get(key), f"history_pool[{i}].{key}")
            if int(x) != x:
                raise HitterJointEngineError(f"history_pool[{i}].{key} must be integer")
            row[key] = int(x)
        pa = row["plate_appearances"]
        if pa < 1 or pa > 9:
            raise HitterJointEngineError(f"history_pool[{i}].plate_appearances outside [1,9]")
        if row["hits"] > pa or row["walks"] > pa or row["hits"] + row["walks"] > pa:
            raise HitterJointEngineError(f"history_pool[{i}] violates PA support")
        if not (row["home_runs"] <= row["extra_base_hits"] <= row["hits"]):
            raise HitterJointEngineError(f"history_pool[{i}] violates HR/XBH/hit nesting")
        if not (row["hits"] <= row["total_bases"] <= 4 * row["hits"]):
            raise HitterJointEngineError(f"history_pool[{i}] violates total-base support")
        if row["runs"] > pa or row["rbi"] > 4 * pa:
            raise HitterJointEngineError(f"history_pool[{i}] violates run/RBI support")
        rows.append(row)
    if len(rows) < 10:
        raise HitterJointEngineError(f"history_pool requires at least 10 prior games; got {len(rows)}")
    return rows


def _value(row: Mapping[str, int], market: str) -> int:
    if market == "HITS": return row["hits"]
    if market == "HOME_RUNS": return row["home_runs"]
    if market == "TOTAL_BASES": return row["total_bases"]
    if market == "RBI": return row["rbi"]
    if market == "RUNS": return row["runs"]
    if market == "STOLEN_BASES": return row["stolen_bases"]
    if market == "BATTER_BB": return row["walks"]
    if market == "EXTRA_BASE_HITS": return row["extra_base_hits"]
    if market == "HITS_RUNS_RBIS": return row["hits"] + row["runs"] + row["rbi"]
    if market == "HITS_RUNS_STOLEN_BASES": return row["hits"] + row["runs"] + row["stolen_bases"]
    if market == "RUNS_RBIS": return row["runs"] + row["rbi"]
    if market == "HITS_STOLEN_BASES": return row["hits"] + row["stolen_bases"]
    if market == "HITS_WALKS_STOLEN_BASES": return row["hits"] + row["walks"] + row["stolen_bases"]
    raise HitterJointEngineError(f"unsupported hitter market {market}")


def price_hitter_market(model_input: Mapping[str, Any]) -> dict[str, Any]:
    market = str(model_input.get("market", "")).upper()
    if market not in HITTER_MARKETS:
        raise HitterJointEngineError(f"unsupported hitter market {market}")
    side = str(model_input.get("side", "")).upper()
    if side not in {"OVER", "UNDER"}:
        raise HitterJointEngineError("side must be OVER or UNDER")
    line = _f(model_input.get("line"), "line")
    features = model_input.get("features")
    if not isinstance(features, Mapping):
        raise HitterJointEngineError("features required")
    pool = _normalize_pool(features.get("history_pool"))
    values = [_value(row, market) for row in pool]
    n = len(values)
    p_over = sum(v > line for v in values) / n
    p_under = sum(v < line for v in values) / n
    p_push = sum(v == line for v in values) / n if float(line).is_integer() else 0.0
    if abs(p_over + p_under + p_push - 1.0) > 1e-12:
        raise HitterJointEngineError("probability mass does not conserve")
    digest = _sha({
        "engine": ENGINE_VERSION, "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"), "feature_source_hash": model_input.get("feature_source_hash"),
        "history_pool": pool,
    })
    return {
        "game_id": model_input.get("game_id"), "market": market, "entity_id": model_input.get("entity_id"),
        "line": line, "side": side, "model_p": p_over if side == "OVER" else p_under,
        "push_p": p_push, "model_input_hash": digest, "engine_version": ENGINE_VERSION,
        "seed_policy": "analytic_empirical_joint_game_rows", "mc_paths": 0,
        "meta": {"history_games": len(pool), "shared_joint_rows": True},
    }
