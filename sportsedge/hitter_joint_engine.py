"""Coherent hitter prop challenger from strictly-prior game rows.

Every prior game is one joint state containing PA and all hitter counting outcomes.
All individual and combination markets are marginals of the same rows, so overlapping
propositions cannot contradict one another. This is the honest v1 until PA-level
play-by-play state is available.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "mlb_hitter_joint_empirical_v2"

HITTER_MARKETS = frozenset({
    "HITS", "HOME_RUNS", "TOTAL_BASES", "RBI", "RUNS", "STOLEN_BASES", "BATTER_BB",
    "EXTRA_BASE_HITS", "SINGLES", "DOUBLES", "TRIPLES", "BATTER_K",
    "HITS_RUNS_RBIS", "HITS_RUNS_STOLEN_BASES", "RUNS_RBIS",
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
        "plate_appearances", "hits", "singles", "doubles", "triples", "home_runs",
        "total_bases", "rbi", "runs", "stolen_bases", "walks", "strikeouts", "extra_base_hits",
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
        if row["hits"] > pa or row["walks"] > pa or row["strikeouts"] > pa:
            raise HitterJointEngineError(f"history_pool[{i}] violates PA support")
        if row["hits"] + row["walks"] > pa:
            raise HitterJointEngineError(f"history_pool[{i}] violates mutually exclusive hit/walk support")
        if row["singles"] + row["doubles"] + row["triples"] + row["home_runs"] != row["hits"]:
            raise HitterJointEngineError(f"history_pool[{i}] hit-type sum mismatch")
        if row["doubles"] + row["triples"] + row["home_runs"] != row["extra_base_hits"]:
            raise HitterJointEngineError(f"history_pool[{i}] XBH arithmetic mismatch")
        expected_tb = row["singles"] + 2 * row["doubles"] + 3 * row["triples"] + 4 * row["home_runs"]
        if expected_tb != row["total_bases"]:
            raise HitterJointEngineError(f"history_pool[{i}] total-base arithmetic mismatch")
        if row["runs"] > pa or row["rbi"] > 4 * pa:
            raise HitterJointEngineError(f"history_pool[{i}] violates run/RBI support")
        rows.append(row)
    if len(rows) < 10:
        raise HitterJointEngineError(f"history_pool requires at least 10 prior games; got {len(rows)}")
    return rows


def _value(row: Mapping[str, int], market: str) -> int:
    keys = {
        "HITS": "hits", "HOME_RUNS": "home_runs", "TOTAL_BASES": "total_bases",
        "RBI": "rbi", "RUNS": "runs", "STOLEN_BASES": "stolen_bases", "BATTER_BB": "walks",
        "EXTRA_BASE_HITS": "extra_base_hits", "SINGLES": "singles", "DOUBLES": "doubles",
        "TRIPLES": "triples", "BATTER_K": "strikeouts",
    }
    if market in keys: return row[keys[market]]
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
    digest = _sha({"engine": ENGINE_VERSION, "game_id": model_input.get("game_id"), "entity_id": model_input.get("entity_id"), "feature_source_hash": model_input.get("feature_source_hash"), "history_pool": pool})
    return {
        "game_id": model_input.get("game_id"), "market": market, "entity_id": model_input.get("entity_id"),
        "line": line, "side": side, "model_p": p_over if side == "OVER" else p_under,
        "push_p": p_push, "model_input_hash": digest, "engine_version": ENGINE_VERSION,
        "seed_policy": "analytic_empirical_joint_game_rows", "mc_paths": 0,
        "meta": {"history_games": len(pool), "shared_joint_rows": True},
    }
