"""Research-only MLB batter home-run challenger.

This module is intentionally outside the canonical runtime package surface. HOME_RUNS
continues to use the behaviorally measured generic baseline in engine_registry. The
candidate here is preserved for point-in-time/holdout work and must not be interpreted
as deployed or promoted merely because the code exists.

The model is price-independent and uses only pregame baseball features. Version 0.2
keeps the stable batter/pitcher/park baseline from v0.1, adds an explicitly bounded
recent-contact challenger, and then shrinks that short-window signal back toward the
stable baseline as a sample-size "haircut". The raw/haircut split is useful for testing
whether short-term Statcast surges add signal without allowing tiny samples to dominate.

External model probabilities (for example BallparkPal) are benchmark-only and are
explicitly banned from the prediction feature payload. ``compare_external_benchmark``
can be used after prediction to measure disagreement without contaminating Model_P.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import exp, isfinite, sqrt
from typing import Any, Mapping

ENGINE_VERSION = "home_runs_research_v0.2"
FEATURE_CONTRACT_VERSION = "hr_batter_pitcher_park_pa_statcast_v2"

# Research constants are deliberately conservative and must be validated/frozen on a
# chronological training set before any promotion. They are not claimed to reproduce
# any third-party proprietary model.
CONTACT_LOG_MULTIPLIER_PER_SIGNAL = 0.12
CONTACT_LOG_MULTIPLIER_CAP = 0.25
CONTACT_RELIABILITY_BBE_PRIOR = 40.0
SURGE_RATIO_THRESHOLD = 1.20
FADE_RATIO_THRESHOLD = 0.90
BATTER_HR_PRIOR_PA = 180.0
PITCHER_HR_PRIOR_PA = 240.0


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
    baseline_home_run_probability: float
    raw_home_run_probability: float
    haircut_home_run_probability: float
    contact_signal: float
    contact_reliability: float
    surge_ratio: float
    surge_label: str


@dataclass(frozen=True)
class HomeRunsBenchmarkOutput:
    benchmark_name: str
    model_probability: float
    benchmark_probability: float
    model_to_benchmark_ratio: float


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


def _optional_finite(
    name: str,
    value: Any,
    lo: float | None = None,
    hi: float | None = None,
) -> float | None:
    if value is None:
        return None
    return _finite(name, value, lo, hi)


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


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _shrink_rate(rate: float, sample: float | None, league: float, prior: float) -> float:
    if sample is None:
        return rate
    return ((rate * sample) + (league * prior)) / (sample + prior)


def _probability_from_per_pa(per_pa: float, pa_pool: list[int]) -> float:
    p_zero = sum((1.0 - per_pa) ** pa for pa in pa_pool) / len(pa_pool)
    return _clamp(1.0 - p_zero, 0.0, 1.0)


def _recent_contact_signal(
    *,
    season_hard_hit: float,
    season_barrel: float,
    season_ev: float,
    recent_hard_hit: float | None,
    recent_barrel: float | None,
    recent_ev: float | None,
    recent_bbe: float | None,
) -> tuple[float, float]:
    supplied = [recent_hard_hit is not None, recent_barrel is not None, recent_ev is not None, recent_bbe is not None]
    if not any(supplied):
        return 0.0, 0.0
    if not all(supplied):
        raise HomeRunsEngineError(
            "recent contact group requires recent_hard_hit_rate, recent_barrel_rate, "
            "recent_avg_exit_velocity, and recent_batted_balls"
        )
    assert recent_hard_hit is not None
    assert recent_barrel is not None
    assert recent_ev is not None
    assert recent_bbe is not None
    if recent_bbe <= 0:
        raise HomeRunsEngineError("recent_batted_balls must be > 0")

    # Scale by meaningful baseball-sized deltas, then cap the aggregate signal. The
    # weights/scale are challenger hypotheses, not fitted coefficients.
    hard_z = (recent_hard_hit - season_hard_hit) / 0.10
    barrel_z = (recent_barrel - season_barrel) / 0.05
    ev_z = (recent_ev - season_ev) / 4.0
    signal = _clamp((0.35 * hard_z) + (0.40 * barrel_z) + (0.25 * ev_z), -2.0, 2.0)
    reliability = recent_bbe / (recent_bbe + CONTACT_RELIABILITY_BBE_PRIOR)
    return signal, reliability


def fair_american_odds(probability: float) -> float:
    p = _finite("probability", probability, 1e-12, 1.0 - 1e-12)
    if p < 0.5:
        return 100.0 * (1.0 - p) / p
    return -100.0 * p / (1.0 - p)


def compare_external_benchmark(
    model_probability: float,
    benchmark_probability: float,
    *,
    benchmark_name: str = "EXTERNAL",
) -> HomeRunsBenchmarkOutput:
    """Compare an already-produced Model_P with an external probability.

    The benchmark is intentionally post-model: it is not accepted by
    ``simulate_home_runs`` and cannot affect Model_P or its input hash.
    """
    model_p = _finite("model_probability", model_probability, 1e-12, 1.0)
    benchmark_p = _finite("benchmark_probability", benchmark_probability, 1e-12, 1.0)
    name = str(benchmark_name or "").strip().upper()
    if not name:
        raise HomeRunsEngineError("benchmark_name required")
    return HomeRunsBenchmarkOutput(
        benchmark_name=name,
        model_probability=model_p,
        benchmark_probability=benchmark_p,
        model_to_benchmark_ratio=model_p / benchmark_p,
    )


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

    banned = (
        "sportsbook", "market_prob", "implied_prob", "novig", "closing_prob", "consensus_prob",
        "ballparkpal", "bpp_probability", "benchmark_probability", "external_model_probability",
    )
    for key in features:
        low = str(key).lower()
        if any(token in low for token in banned):
            raise HomeRunsEngineError(f"sportsbook/external-model-derived feature banned: {key}")

    batter_hr = _finite("batter_hr_rate", features.get("batter_hr_rate"), 1e-8, 0.5)
    pitcher_hr = _finite("pitcher_hr_rate_allowed", features.get("pitcher_hr_rate_allowed"), 1e-8, 0.5)
    league_hr = _finite("league_hr_rate", features.get("league_hr_rate"), 1e-8, 0.5)
    park = _finite("park_hr_factor", features.get("park_hr_factor"), 0.1, 5.0)
    barrel = _finite("barrel_rate", features.get("barrel_rate"), 0.0, 1.0)
    hard_hit = _finite("hard_hit_rate", features.get("hard_hit_rate"), 0.0, 1.0)
    avg_ev = _finite("avg_exit_velocity", features.get("avg_exit_velocity"), 50.0, 120.0)
    pa_pool = _pa_pool(features.get("pa_pool"))

    batter_pa = _optional_finite("batter_pa_sample", features.get("batter_pa_sample"), 1.0, 5000.0)
    pitcher_pa = _optional_finite("pitcher_pa_sample", features.get("pitcher_pa_sample"), 1.0, 5000.0)
    recent_hard_hit = _optional_finite("recent_hard_hit_rate", features.get("recent_hard_hit_rate"), 0.0, 1.0)
    recent_barrel = _optional_finite("recent_barrel_rate", features.get("recent_barrel_rate"), 0.0, 1.0)
    recent_ev = _optional_finite("recent_avg_exit_velocity", features.get("recent_avg_exit_velocity"), 50.0, 120.0)
    recent_bbe = _optional_finite("recent_batted_balls", features.get("recent_batted_balls"), 0.0, 1000.0)

    lineup_status = str(model_input.get("lineup_status", ""))
    if lineup_status not in {"CONFIRMED", "PROJECTED"}:
        raise HomeRunsEngineError("invalid lineup_status")
    require_confirmed = model_input.get("require_confirmed_lineup", False)
    if type(require_confirmed) is not bool:
        raise HomeRunsEngineError("require_confirmed_lineup must be boolean")
    if require_confirmed and lineup_status != "CONFIRMED":
        raise HomeRunsEngineError("confirmed lineup required")

    stable_batter = _shrink_rate(batter_hr, batter_pa, league_hr, BATTER_HR_PRIOR_PA)
    stable_pitcher = _shrink_rate(pitcher_hr, pitcher_pa, league_hr, PITCHER_HR_PRIOR_PA)
    matchup_rate = sqrt(stable_batter * stable_pitcher)
    baseline_per_pa = _clamp(matchup_rate * park, 1e-8, 0.5)

    signal, reliability = _recent_contact_signal(
        season_hard_hit=hard_hit,
        season_barrel=barrel,
        season_ev=avg_ev,
        recent_hard_hit=recent_hard_hit,
        recent_barrel=recent_barrel,
        recent_ev=recent_ev,
        recent_bbe=recent_bbe,
    )
    raw_log_uplift = _clamp(
        CONTACT_LOG_MULTIPLIER_PER_SIGNAL * signal,
        -CONTACT_LOG_MULTIPLIER_CAP,
        CONTACT_LOG_MULTIPLIER_CAP,
    )
    raw_per_pa = _clamp(baseline_per_pa * exp(raw_log_uplift), 1e-8, 0.5)
    haircut_per_pa = _clamp(baseline_per_pa * exp(raw_log_uplift * reliability), 1e-8, 0.5)

    baseline_p = _probability_from_per_pa(baseline_per_pa, pa_pool)
    raw_p = _probability_from_per_pa(raw_per_pa, pa_pool)
    haircut_p = _probability_from_per_pa(haircut_per_pa, pa_pool)
    surge_ratio = raw_p / max(baseline_p, 1e-12)
    if surge_ratio >= SURGE_RATIO_THRESHOLD:
        surge_label = "SURGE"
    elif surge_ratio < FADE_RATIO_THRESHOLD:
        surge_label = "FADE"
    else:
        surge_label = "HOLD"

    mean_pa = sum(pa_pool) / len(pa_pool)
    expected_hr = mean_pa * haircut_per_pa

    probs: dict[float, float] = {}
    for raw_threshold in thresholds:
        threshold = _finite("threshold", raw_threshold, 0.0)
        if threshold != 0.5:
            raise HomeRunsEngineError("research HR engine currently supports only 0.5")
        probs[threshold] = haircut_p

    digest = _canonical_hash({
        "engine": ENGINE_VERSION,
        "feature_contract": FEATURE_CONTRACT_VERSION,
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
            "batter_pa_sample": batter_pa,
            "pitcher_pa_sample": pitcher_pa,
            "recent_hard_hit_rate": recent_hard_hit,
            "recent_barrel_rate": recent_barrel,
            "recent_avg_exit_velocity": recent_ev,
            "recent_batted_balls": recent_bbe,
        },
        "research_constants": {
            "contact_log_multiplier_per_signal": CONTACT_LOG_MULTIPLIER_PER_SIGNAL,
            "contact_log_multiplier_cap": CONTACT_LOG_MULTIPLIER_CAP,
            "contact_reliability_bbe_prior": CONTACT_RELIABILITY_BBE_PRIOR,
            "batter_hr_prior_pa": BATTER_HR_PRIOR_PA,
            "pitcher_hr_prior_pa": PITCHER_HR_PRIOR_PA,
        },
        "lineup_status": lineup_status,
    })
    return HomeRunsModelOutput(
        engine_version=ENGINE_VERSION,
        model_input_hash=digest,
        seed_policy="analytic_empirical_pa_pool_with_reliability_haircut",
        mc_paths=0,
        lineup_status=lineup_status,
        per_pa_hr_probability=haircut_per_pa,
        expected_home_runs=expected_hr,
        probs=probs,
        baseline_home_run_probability=baseline_p,
        raw_home_run_probability=raw_p,
        haircut_home_run_probability=haircut_p,
        contact_signal=signal,
        contact_reliability=reliability,
        surge_ratio=surge_ratio,
        surge_label=surge_label,
    )
