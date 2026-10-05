"""Coherent hitter props from strictly-prior joint game rows with finite-sample shrinkage.

Recent form remains the primary likelihood. When a separately supplied older
strictly-prior pool is available, it contributes at most the recent effective
sample size as an empirical prior. Sportsbook prices are never model inputs.
"""
from __future__ import annotations

import hashlib
import json
from math import isfinite
from typing import Any, Mapping, Sequence

from .mlb_empirical_bayes import (
    effective_sample_size,
    feasible_settlements,
    posterior_settlement_mass,
)

ENGINE_VERSION = "mlb_hitter_joint_empirical_bayes_v6_long_window_prior"
LONG_WINDOW_PRIOR_POLICY = "STRICT_PRIOR_EMPIRICAL_POOL_CAPPED_AT_RECENT_EFFECTIVE_N"
HITTER_MARKETS = frozenset({
    "HITS", "HOME_RUNS", "TOTAL_BASES", "RBI", "RUNS", "STOLEN_BASES",
    "BATTER_BB", "EXTRA_BASE_HITS", "SINGLES", "DOUBLES", "TRIPLES",
    "BATTER_K", "HITS_RUNS_RBIS", "HITS_RUNS_STOLEN_BASES", "RUNS_RBIS",
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
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def _normalize_pool(raw: Any, *, name: str = "history_pool", minimum: int = 10) -> list[dict[str, int]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise HitterJointEngineError(f"{name} must be a sequence")
    required = (
        "plate_appearances", "hits", "singles", "doubles", "triples", "home_runs",
        "total_bases", "rbi", "runs", "stolen_bases", "walks", "strikeouts",
        "extra_base_hits",
    )
    rows: list[dict[str, int]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise HitterJointEngineError(f"{name}[{i}] must be object")
        row: dict[str, int] = {}
        for key in required:
            x = _f(item.get(key), f"{name}[{i}].{key}")
            if int(x) != x:
                raise HitterJointEngineError(f"{name}[{i}].{key} must be integer")
            row[key] = int(x)
        pa = row["plate_appearances"]
        if pa < 1 or pa > 9:
            raise HitterJointEngineError(f"{name}[{i}].plate_appearances outside [1,9]")
        if row["hits"] > pa or row["walks"] > pa or row["strikeouts"] > pa:
            raise HitterJointEngineError(f"{name}[{i}] violates PA support")
        if row["hits"] + row["walks"] > pa:
            raise HitterJointEngineError(f"{name}[{i}] violates mutually exclusive hit/walk support")
        if row["singles"] + row["doubles"] + row["triples"] + row["home_runs"] != row["hits"]:
            raise HitterJointEngineError(f"{name}[{i}] hit-type sum mismatch")
        if row["doubles"] + row["triples"] + row["home_runs"] != row["extra_base_hits"]:
            raise HitterJointEngineError(f"{name}[{i}] XBH arithmetic mismatch")
        if (
            row["singles"]
            + 2 * row["doubles"]
            + 3 * row["triples"]
            + 4 * row["home_runs"]
            != row["total_bases"]
        ):
            raise HitterJointEngineError(f"{name}[{i}] total-base arithmetic mismatch")
        # A player can enter as a pinch runner, score, and later record plate
        # appearances. That makes runs == PA + 1 legal; larger gaps are not.
        if row["runs"] > pa + 1 or row["rbi"] > 4 * pa:
            raise HitterJointEngineError(f"{name}[{i}] violates run/RBI support")
        rows.append(row)
    if len(rows) < minimum:
        raise HitterJointEngineError(
            f"{name} requires at least {minimum} prior games; got {len(rows)}"
        )
    return rows


def _normalize_weights(raw: Any, n: int, *, name: str = "history_weights") -> list[float]:
    if raw is None:
        return [1.0 / n] * n
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != n:
        raise HitterJointEngineError(f"{name} must align one-to-one with its pool")
    vals = [_f(v, f"{name}[{i}]") for i, v in enumerate(raw)]
    if any(v <= 0 for v in vals):
        raise HitterJointEngineError(f"{name} must be strictly positive")
    total = sum(vals)
    if not isfinite(total) or total <= 0:
        raise HitterJointEngineError(f"{name} total invalid")
    return [v / total for v in vals]


def _value(row: Mapping[str, int], market: str) -> int:
    keys = {
        "HITS": "hits",
        "HOME_RUNS": "home_runs",
        "TOTAL_BASES": "total_bases",
        "RBI": "rbi",
        "RUNS": "runs",
        "STOLEN_BASES": "stolen_bases",
        "BATTER_BB": "walks",
        "EXTRA_BASE_HITS": "extra_base_hits",
        "SINGLES": "singles",
        "DOUBLES": "doubles",
        "TRIPLES": "triples",
        "BATTER_K": "strikeouts",
    }
    if market in keys:
        return row[keys[market]]
    if market == "HITS_RUNS_RBIS":
        return row["hits"] + row["runs"] + row["rbi"]
    if market == "HITS_RUNS_STOLEN_BASES":
        return row["hits"] + row["runs"] + row["stolen_bases"]
    if market == "RUNS_RBIS":
        return row["runs"] + row["rbi"]
    if market == "HITS_STOLEN_BASES":
        return row["hits"] + row["stolen_bases"]
    if market == "HITS_WALKS_STOLEN_BASES":
        return row["hits"] + row["walks"] + row["stolen_bases"]
    raise HitterJointEngineError(f"unsupported hitter market {market}")


def _settlement_mass(values: Sequence[int], weights: Sequence[float], line: float) -> tuple[float, float, float]:
    over = sum(w for v, w in zip(values, weights) if v > line)
    under = sum(w for v, w in zip(values, weights) if v < line)
    push = (
        sum(w for v, w in zip(values, weights) if v == line)
        if float(line).is_integer()
        else 0.0
    )
    if abs(over + under + push - 1.0) > 1e-12:
        raise HitterJointEngineError("probability mass does not conserve")
    return float(over), float(under), float(push)


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
    weights = _normalize_weights(features.get("history_weights"), len(pool))
    values = [_value(row, market) for row in pool]
    raw_over, raw_under, raw_push = _settlement_mass(values, weights, line)
    n_eff = effective_sample_size(weights, len(pool))

    combined_over = raw_over
    combined_under = raw_under
    combined_push = raw_push
    combined_n = float(n_eff)
    prior_meta = None
    prior_pool_for_identity = None
    prior_weights_for_identity = None

    if features.get("prior_pool") is not None:
        prior_pool = _normalize_pool(features.get("prior_pool"), name="prior_pool")
        prior_weights = _normalize_weights(
            features.get("prior_weights"), len(prior_pool), name="prior_weights"
        )
        prior_values = [_value(row, market) for row in prior_pool]
        prior_over, prior_under, prior_push = _settlement_mass(
            prior_values, prior_weights, line
        )
        prior_n_eff = effective_sample_size(prior_weights, len(prior_pool))
        prior_strength = min(float(prior_n_eff), float(n_eff))
        combined_n = float(n_eff) + prior_strength
        combined_over = (
            float(n_eff) * raw_over + prior_strength * prior_over
        ) / combined_n
        combined_under = (
            float(n_eff) * raw_under + prior_strength * prior_under
        ) / combined_n
        combined_push = (
            float(n_eff) * raw_push + prior_strength * prior_push
        ) / combined_n
        prior_meta = {
            "policy": LONG_WINDOW_PRIOR_POLICY,
            "history_games": len(prior_pool),
            "effective_history_games": float(prior_n_eff),
            "strength": float(prior_strength),
            "raw_over": float(prior_over),
            "raw_under": float(prior_under),
            "raw_push": float(prior_push),
        }
        prior_pool_for_identity = prior_pool
        prior_weights_for_identity = prior_weights

    post = posterior_settlement_mass(
        over_mass=combined_over,
        under_mass=combined_under,
        push_mass=combined_push,
        effective_n=combined_n,
        has_push=float(line).is_integer(),
        feasible=feasible_settlements(line, lower=0),
    )
    p = post["p_over"] if side == "OVER" else post["p_under"]

    digest = _sha({
        "engine": ENGINE_VERSION,
        "game_id": model_input.get("game_id"),
        "entity_id": model_input.get("entity_id"),
        "feature_source_hash": model_input.get("feature_source_hash"),
        "history_pool": pool,
        "history_weights": weights,
        "prior_pool": prior_pool_for_identity,
        "prior_weights": prior_weights_for_identity,
    })
    meta = {
        "history_games": len(pool),
        "shared_joint_rows": True,
        "weighted": features.get("history_weights") is not None,
        "raw_empirical_p": float(raw_over if side == "OVER" else raw_under),
        "raw_push_p": float(raw_push),
        "effective_history_games": float(n_eff),
        "posterior_prior": post["prior"],
        "posterior_sd": float(
            post["posterior_sd_over"] if side == "OVER" else post["posterior_sd_under"]
        ),
    }
    if prior_meta is not None:
        meta["long_window_prior"] = prior_meta

    return {
        "game_id": model_input.get("game_id"),
        "market": market,
        "entity_id": model_input.get("entity_id"),
        "line": line,
        "side": side,
        "model_p": float(p),
        "push_p": float(post["p_push"]),
        "model_input_hash": digest,
        "engine_version": ENGINE_VERSION,
        "seed_policy": "analytic_empirical_bayes_recent_plus_capped_prior_joint_game_rows",
        "mc_paths": 0,
        "meta": meta,
    }
