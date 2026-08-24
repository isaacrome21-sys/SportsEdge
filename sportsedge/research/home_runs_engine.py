"""Research-only MLB batter home-run challenger.

This module is intentionally outside the canonical runtime package surface. HOME_RUNS
continues to use the behaviorally measured generic baseline in engine_registry. The
candidate here is preserved for future point-in-time/holdout work and must not be
interpreted as deployed or promoted merely because the code exists.

The model is price-independent and uses only pregame baseball features. Statcast
contact-quality fields are required and hashed for provenance, but are not assigned
fitted coefficients until a historical point-in-time training and untouched-holdout
fit freezes them.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite, sqrt
from typing import Any, Mapping

ENGINE_VERSION = "home_runs_research_v0.1"
FEATURE_CONTRACT_VERSION = "hr_batter_pitcher_park_pa_statcast_v1"


class HomeRunsEngineError(ValueError):
    pass


@dataclass(frozen=True)
class HomeRunsModelOutput:
    engine_version: str
    model_input_hash: str
    seed_policy: str
    mc_paths: int
    lineup_status: str
    per_pa_hr_probability: float
    expected_home_runs: float
    probs: dict[float, float]


def _finite(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise HomeRunsEngineError(f"invalid {name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HomeRunsEngineError(f"invalid {name}") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise HomeRunsEngineError(f"invalid {name}")
    return out


def _pa_pool(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)) or not value:
        raise HomeRunsEngineError("pa_pool must be non-empty")
    out: list[int] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 9:
            raise HomeRunsEngineError("pa_pool must contain integer PA counts in [0,9]")
        out.append(raw)
    return out


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def simulate_home_runs(model_input: Mapping[str, Any], thresholds: tuple[float, ...] = (0.5,)) -> HomeRunsModelOutput:
    if not isinstance(model_input, Mapping):
        raise HomeRunsEngineError("model_input must be a mapping")
    if model_input.get("market") != "home_runs":
        raise HomeRunsEngineError("wrong market for Home Runs engine")
    if not model_input.get("build_hash"):
        raise HomeRunsEngineError("missing build_hash")

    features = model_input.get("features")
    if not isinstance(features, Mapping):
        raise HomeRunsEngineError("features must be a mapping")

    banned = ("sportsbook", "market_prob", "implied_prob", "novig", "closing_prob", "consensus_prob")
    for key in features:
        low = str(key).lower()
        if any(token in low for token in banned):
            raise HomeRunsEngineError(f"sportsbook-derived feature banned: {key}")

    batter_hr = _finite("batter_hr_rate", features.get("batter_hr_rate"), 1e-8, 0.5)
    pitcher_hr = _finite("pitcher_hr_rate_allowed", features.get("pitcher_hr_rate_allowed"), 1e-8, 0.5)
    league_hr = _finite("league_hr_rate", features.get("league_hr_rate"), 1e-8, 0.5)
    park = _finite("park_hr_factor", features.get("park_hr_factor"), 0.1, 5.0)
    barrel = _finite("barrel_rate", features.get("barrel_rate"), 0.0, 1.0)
    hard_hit = _finite("hard_hit_rate", features.get("hard_hit_rate"), 0.0, 1.0)
    avg_ev = _finite("avg_exit_velocity", features.get("avg_exit_velocity"), 50.0, 120.0)
    pa_pool = _pa_pool(features.get("pa_pool"))

    lineup_status = str(model_input.get("lineup_status", ""))
    if lineup_status not in {"CONFIRMED", "PROJECTED"}:
        raise HomeRunsEngineError("invalid lineup_status")
    require_confirmed = model_input.get("require_confirmed_lineup", False)
    if type(require_confirmed) is not bool:
        raise HomeRunsEngineError("require_confirmed_lineup must be boolean")
    if require_confirmed and lineup_status != "CONFIRMED":
        raise HomeRunsEngineError("confirmed lineup required")

    # Transparent unfitted baseline: combine independent batter/pitcher HR rates
    # symmetrically around league average, then apply the directional HR park factor.
    # Contact-quality fields are captured in the feature contract for later PIT fit,
    # but are deliberately not given arbitrary coefficients here.
    matchup_rate = sqrt(batter_hr * pitcher_hr)
    per_pa = max(1e-8, min(0.5, matchup_rate * park))

    mean_pa = sum(pa_pool) / len(pa_pool)
    expected_hr = mean_pa * per_pa

    probs: dict[float, float] = {}
    for raw_threshold in thresholds:
        threshold = _finite("threshold", raw_threshold, 0.0)
        if threshold != 0.5:
            raise HomeRunsEngineError("research HR engine currently supports only 0.5")
        p_zero = sum((1.0 - per_pa) ** pa for pa in pa_pool) / len(pa_pool)
        probs[threshold] = 1.0 - p_zero

    digest = _canonical_hash({
        "engine": ENGINE_VERSION,
        "build_hash": model_input.get("build_hash"),
        "features": {
            "batter_hr_rate": batter_hr,
            "pitcher_hr_rate_allowed": pitcher_hr,
            "league_hr_rate": league_hr,
            "park_hr_factor": park,
            "barrel_rate": barrel,
            "hard_hit_rate": hard_hit,
            "avg_exit_velocity": avg_ev,
            "pa_pool": pa_pool,
        },
        "lineup_status": lineup_status,
    })
    return HomeRunsModelOutput(
        ENGINE_VERSION,
        digest,
        "analytic_empirical_pa_pool",
        0,
        lineup_status,
        per_pa,
        expected_hr,
        probs,
    )
