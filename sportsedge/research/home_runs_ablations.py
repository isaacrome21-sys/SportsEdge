"""Research-only HOME_RUNS v0.3 ablation arms.

v0.2 is frozen. Each v0.3 arm starts from the exact same v0.2 haircut probability
and changes exactly one feature family: platoon, park/weather, or directional
geometry. The arms are intentionally not combined here; combination can only be
considered after isolated point-in-time evidence shows which families survive.

All modifiers are baseball-derived and price-independent. The caps and shrinkage
priors are research hypotheses, not promotion evidence.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import exp, isfinite, log
from typing import Any, Mapping

PLATOON_ARM = "PLATOON_V03"
PARK_WEATHER_ARM = "PARK_WEATHER_V03"
GEOMETRY_ARM = "GEOMETRY_V03"
V03_ARMS = (PLATOON_ARM, PARK_WEATHER_ARM, GEOMETRY_ARM)

# Bounded so no single unvalidated family can overwhelm the frozen v0.2 output.
MAX_ABS_LOG_UPLIFT = 0.22
PLATOON_BATTER_PA_PRIOR = 120.0
PLATOON_PITCHER_PA_PRIOR = 160.0
GEOMETRY_BBE_PRIOR = 100.0

_BANNED = (
    "sportsbook", "american_odds", "decimal_odds", "market_prob", "implied_prob",
    "novig", "no_vig", "closing", "consensus_prob", "ballparkpal", "bpp_probability",
    "benchmark_probability", "external_model_probability",
)


class HomeRunsAblationError(ValueError):
    pass


@dataclass(frozen=True)
class HomeRunsAblationOutput:
    arm: str
    base_probability: float
    probability: float
    centered_multiplier: float
    reliability: float
    applied_log_uplift: float
    diagnostics: dict[str, float]


def _finite(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise HomeRunsAblationError(f"invalid {name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HomeRunsAblationError(f"invalid {name}") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise HomeRunsAblationError(f"invalid {name}")
    return out


def _assert_market_blind(value: Any, path: str = "features") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).strip().lower()
            if any(token in name for token in _BANNED):
                raise HomeRunsAblationError(f"market/external field prohibited: {path}.{key}")
            _assert_market_blind(child, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, child in enumerate(value):
            _assert_market_blind(child, f"{path}[{i}]")


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _pa_pool(value: Any) -> list[int]:
    if not isinstance(value, (list, tuple)) or not value:
        raise HomeRunsAblationError("pa_pool must be non-empty")
    out: list[int] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 9:
            raise HomeRunsAblationError("pa_pool must contain integer PA in [0,9]")
        out.append(raw)
    return out


def _game_probability(per_pa: float, pa_pool: list[int]) -> float:
    return _clamp(
        1.0 - sum((1.0 - per_pa) ** pa for pa in pa_pool) / len(pa_pool),
        0.0,
        1.0,
    )


def _per_pa_from_game_probability(game_probability: float, pa_pool: list[int]) -> float:
    """Invert the empirical-PA game probability monotonically by bisection."""
    target = _finite("base_probability", game_probability, 1e-12, 1.0 - 1e-12)
    lo, hi = 1e-12, 0.5
    if _game_probability(hi, pa_pool) < target:
        raise HomeRunsAblationError("base probability exceeds supported per-PA range")
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _game_probability(mid, pa_pool) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _apply(
    *,
    arm: str,
    base_probability: Any,
    pa_pool: Any,
    centered_multiplier: Any,
    reliability: Any,
    diagnostics: Mapping[str, float],
) -> HomeRunsAblationOutput:
    if arm not in V03_ARMS:
        raise HomeRunsAblationError("unknown v0.3 arm")
    pool = _pa_pool(pa_pool)
    base_p = _finite("base_probability", base_probability, 1e-12, 1.0 - 1e-12)
    multiplier = _finite("centered_multiplier", centered_multiplier, 0.20, 5.0)
    rel = _finite("reliability", reliability, 0.0, 1.0)
    base_per_pa = _per_pa_from_game_probability(base_p, pool)
    log_uplift = _clamp(log(multiplier) * rel, -MAX_ABS_LOG_UPLIFT, MAX_ABS_LOG_UPLIFT)
    adjusted_per_pa = _clamp(base_per_pa * exp(log_uplift), 1e-12, 0.5)
    adjusted_p = _game_probability(adjusted_per_pa, pool)
    return HomeRunsAblationOutput(
        arm=arm,
        base_probability=base_p,
        probability=adjusted_p,
        centered_multiplier=multiplier,
        reliability=rel,
        applied_log_uplift=log_uplift,
        diagnostics={str(k): float(v) for k, v in diagnostics.items()},
    )


def platoon_v03(
    *,
    base_probability: Any,
    pa_pool: Any,
    batter_hr_rate_vs_hand: Any,
    batter_hr_rate_overall: Any,
    batter_split_pa: Any,
    pitcher_hr_rate_allowed_vs_hand: Any,
    pitcher_hr_rate_allowed_overall: Any,
    pitcher_split_pa: Any,
) -> HomeRunsAblationOutput:
    features = {
        "batter_hr_rate_vs_hand": batter_hr_rate_vs_hand,
        "batter_hr_rate_overall": batter_hr_rate_overall,
        "batter_split_pa": batter_split_pa,
        "pitcher_hr_rate_allowed_vs_hand": pitcher_hr_rate_allowed_vs_hand,
        "pitcher_hr_rate_allowed_overall": pitcher_hr_rate_allowed_overall,
        "pitcher_split_pa": pitcher_split_pa,
    }
    _assert_market_blind(features)
    bh = _finite("batter_hr_rate_vs_hand", batter_hr_rate_vs_hand, 1e-8, 0.5)
    bo = _finite("batter_hr_rate_overall", batter_hr_rate_overall, 1e-8, 0.5)
    bpa = _finite("batter_split_pa", batter_split_pa, 0.0)
    ph = _finite("pitcher_hr_rate_allowed_vs_hand", pitcher_hr_rate_allowed_vs_hand, 1e-8, 0.5)
    po = _finite("pitcher_hr_rate_allowed_overall", pitcher_hr_rate_allowed_overall, 1e-8, 0.5)
    ppa = _finite("pitcher_split_pa", pitcher_split_pa, 0.0)

    # Center at each player's overall rate, then shrink the handedness departure
    # toward neutral as the split sample gets smaller.
    batter_ratio = bh / bo
    pitcher_ratio = ph / po
    centered = (batter_ratio * pitcher_ratio) ** 0.5
    rb = bpa / (bpa + PLATOON_BATTER_PA_PRIOR)
    rp = ppa / (ppa + PLATOON_PITCHER_PA_PRIOR)
    reliability = (rb * rp) ** 0.5
    return _apply(
        arm=PLATOON_ARM,
        base_probability=base_probability,
        pa_pool=pa_pool,
        centered_multiplier=centered,
        reliability=reliability,
        diagnostics={
            "batter_ratio": batter_ratio,
            "pitcher_ratio": pitcher_ratio,
            "batter_split_reliability": rb,
            "pitcher_split_reliability": rp,
        },
    )


def park_weather_v03(
    *,
    base_probability: Any,
    pa_pool: Any,
    generic_park_hr_factor: Any,
    handed_park_hr_factor: Any,
    weather_hr_multiplier: Any,
    weather_confidence: Any = 1.0,
) -> HomeRunsAblationOutput:
    features = {
        "generic_park_hr_factor": generic_park_hr_factor,
        "handed_park_hr_factor": handed_park_hr_factor,
        "weather_hr_multiplier": weather_hr_multiplier,
        "weather_confidence": weather_confidence,
    }
    _assert_market_blind(features)
    generic = _finite("generic_park_hr_factor", generic_park_hr_factor, 0.1, 5.0)
    handed = _finite("handed_park_hr_factor", handed_park_hr_factor, 0.1, 5.0)
    weather = _finite("weather_hr_multiplier", weather_hr_multiplier, 0.5, 1.5)
    confidence = _finite("weather_confidence", weather_confidence, 0.0, 1.0)

    # v0.2 already includes a generic park factor. The arm therefore applies only
    # the handedness correction relative to that generic factor, plus weather.
    handed_correction = handed / generic
    centered = handed_correction * weather
    return _apply(
        arm=PARK_WEATHER_ARM,
        base_probability=base_probability,
        pa_pool=pa_pool,
        centered_multiplier=centered,
        reliability=confidence,
        diagnostics={
            "handed_park_correction": handed_correction,
            "weather_hr_multiplier": weather,
            "weather_confidence": confidence,
        },
    )


def geometry_v03(
    *,
    base_probability: Any,
    pa_pool: Any,
    pull_share: Any,
    center_share: Any,
    oppo_share: Any,
    pull_park_hr_factor: Any,
    center_park_hr_factor: Any,
    oppo_park_hr_factor: Any,
    directional_bbe: Any,
) -> HomeRunsAblationOutput:
    features = {
        "pull_share": pull_share,
        "center_share": center_share,
        "oppo_share": oppo_share,
        "pull_park_hr_factor": pull_park_hr_factor,
        "center_park_hr_factor": center_park_hr_factor,
        "oppo_park_hr_factor": oppo_park_hr_factor,
        "directional_bbe": directional_bbe,
    }
    _assert_market_blind(features)
    pull = _finite("pull_share", pull_share, 0.0, 1.0)
    center = _finite("center_share", center_share, 0.0, 1.0)
    oppo = _finite("oppo_share", oppo_share, 0.0, 1.0)
    total_share = pull + center + oppo
    if abs(total_share - 1.0) > 0.02:
        raise HomeRunsAblationError("directional shares must sum to 1 within 0.02")
    # Normalize tiny rounding drift so the multiplier stays centered.
    pull, center, oppo = pull / total_share, center / total_share, oppo / total_share
    pf_pull = _finite("pull_park_hr_factor", pull_park_hr_factor, 0.1, 5.0)
    pf_center = _finite("center_park_hr_factor", center_park_hr_factor, 0.1, 5.0)
    pf_oppo = _finite("oppo_park_hr_factor", oppo_park_hr_factor, 0.1, 5.0)
    bbe = _finite("directional_bbe", directional_bbe, 0.0)
    centered = pull * pf_pull + center * pf_center + oppo * pf_oppo
    reliability = bbe / (bbe + GEOMETRY_BBE_PRIOR)
    return _apply(
        arm=GEOMETRY_ARM,
        base_probability=base_probability,
        pa_pool=pa_pool,
        centered_multiplier=centered,
        reliability=reliability,
        diagnostics={
            "weighted_directional_park_factor": centered,
            "directional_reliability": reliability,
        },
    )


def evaluate_isolated_v03_arms(
    *,
    base_probability: Any,
    pa_pool: Any,
    platoon: Mapping[str, Any] | None = None,
    park_weather: Mapping[str, Any] | None = None,
    geometry: Mapping[str, Any] | None = None,
) -> dict[str, HomeRunsAblationOutput]:
    """Evaluate independent arms; never compound one arm on another."""
    outputs: dict[str, HomeRunsAblationOutput] = {}
    if platoon is not None:
        outputs[PLATOON_ARM] = platoon_v03(
            base_probability=base_probability, pa_pool=pa_pool, **dict(platoon)
        )
    if park_weather is not None:
        outputs[PARK_WEATHER_ARM] = park_weather_v03(
            base_probability=base_probability, pa_pool=pa_pool, **dict(park_weather)
        )
    if geometry is not None:
        outputs[GEOMETRY_ARM] = geometry_v03(
            base_probability=base_probability, pa_pool=pa_pool, **dict(geometry)
        )
    return outputs
