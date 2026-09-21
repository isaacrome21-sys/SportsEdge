"""Research-only MLB batter home-run matchup challenger.

This challenger keeps sportsbook prices downstream from the probability model.  It
uses transparent additive stabilization for batter/pitcher HR rates, an empirical
plate-appearance distribution, and optional shared park/weather scenarios.  Contact
quality is retained for provenance but intentionally receives no arbitrary weight
until a point-in-time fitted artifact exists.

Existence of this module does not grant Model_P, Truth Gate passage, promotion,
staking, or OFFICIAL authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import isfinite, sqrt
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "mlb_home_run_matchup_research_v0.1"
FEATURE_CONTRACT_VERSION = "mlb_hr_batter_pitcher_pa_environment_v1"


class HomeRunMatchupError(ValueError):
    """Raised when a research input fails the fail-closed contract."""


@dataclass(frozen=True)
class HomeRunMatchupOutput:
    engine_version: str
    feature_contract_version: str
    model_input_hash: str
    batter_hr_rate_stabilized: float
    pitcher_hr_rate_allowed_stabilized: float
    neutral_per_pa_hr_probability: float
    per_pa_hr_probability: float
    expected_home_runs: float
    home_run_probability: float
    no_home_run_probability: float
    mean_plate_appearances: float
    environment_scenario_count: int
    contact_quality_weighted: bool


def _finite(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise HomeRunMatchupError(f"invalid {name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise HomeRunMatchupError(f"invalid {name}") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise HomeRunMatchupError(f"invalid {name}")
    return out


def _count(name: str, value: Any, lo: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        raise HomeRunMatchupError(f"invalid {name}")
    return value


def _pa_pool(value: Any) -> list[int]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise HomeRunMatchupError("pa_pool must be a non-empty sequence")
    out: list[int] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, int) or not 0 <= raw <= 9:
            raise HomeRunMatchupError("pa_pool must contain integer PA counts in [0,9]")
        out.append(raw)
    return out


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise HomeRunMatchupError("source_hashes must be a non-empty mapping")
    out: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        digest = str(raw_value).strip()
        if not key or not digest:
            raise HomeRunMatchupError("source_hashes keys and values must be non-empty")
        out[key] = digest
    return dict(sorted(out.items()))


def _reject_book_features(features: Mapping[str, Any]) -> None:
    banned = (
        "sportsbook",
        "book_prob",
        "market_prob",
        "implied_prob",
        "novig",
        "closing_prob",
        "consensus_prob",
        "bet_percentage",
        "money_percentage",
    )
    for key in features:
        low = str(key).lower()
        if any(token in low for token in banned):
            raise HomeRunMatchupError(f"sportsbook-derived feature banned: {key}")


def _stabilized_rate(successes: int, trials: int, prior_mean: float, prior_weight: float, name: str) -> float:
    if successes > trials:
        raise HomeRunMatchupError(f"{name} successes exceed trials")
    if trials == 0 and prior_weight == 0:
        raise HomeRunMatchupError(f"{name} has no observations or prior weight")
    return (successes + prior_mean * prior_weight) / (trials + prior_weight)


def _environment_scenarios(
    raw: Any,
    default_park: float,
    default_weather: float,
) -> list[tuple[float, float, float]]:
    if raw is None:
        return [(1.0, default_park, default_weather)]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise HomeRunMatchupError("shared_environment_scenarios must be a non-empty sequence")
    parsed: list[tuple[float, float, float]] = []
    weight_sum = 0.0
    for idx, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise HomeRunMatchupError(f"environment scenario {idx} must be a mapping")
        weight = _finite(f"scenario[{idx}].weight", item.get("weight"), 1e-12)
        park = _finite(f"scenario[{idx}].park_hr_factor", item.get("park_hr_factor"), 0.25, 4.0)
        weather = _finite(f"scenario[{idx}].weather_hr_factor", item.get("weather_hr_factor"), 0.25, 4.0)
        parsed.append((weight, park, weather))
        weight_sum += weight
    return [(weight / weight_sum, park, weather) for weight, park, weather in parsed]


def simulate_home_run_matchup(model_input: Mapping[str, Any]) -> HomeRunMatchupOutput:
    if not isinstance(model_input, Mapping):
        raise HomeRunMatchupError("model_input must be a mapping")
    if model_input.get("market") != "home_runs":
        raise HomeRunMatchupError("wrong market for MLB home-run challenger")
    if model_input.get("game_status") != "PRE_GAME":
        raise HomeRunMatchupError("home-run challenger is pregame only")
    if not model_input.get("build_hash"):
        raise HomeRunMatchupError("missing build_hash")

    lineup_status = model_input.get("lineup_status")
    if lineup_status != "CONFIRMED":
        raise HomeRunMatchupError("confirmed lineup required")

    features = model_input.get("features")
    if not isinstance(features, Mapping):
        raise HomeRunMatchupError("features must be a mapping")
    _reject_book_features(features)
    source_hashes = _source_hashes(model_input.get("source_hashes"))

    league_hr = _finite("league_hr_rate", features.get("league_hr_rate"), 1e-8, 0.5)
    batter_prior_weight = _finite("batter_prior_weight", features.get("batter_prior_weight"), 0.0, 5000.0)
    pitcher_prior_weight = _finite("pitcher_prior_weight", features.get("pitcher_prior_weight"), 0.0, 5000.0)

    batter_pa = _count("batter_pa", features.get("batter_pa"))
    batter_hr = _count("batter_home_runs", features.get("batter_home_runs"))
    pitcher_bf = _count("pitcher_batters_faced", features.get("pitcher_batters_faced"))
    pitcher_hr = _count("pitcher_home_runs_allowed", features.get("pitcher_home_runs_allowed"))

    batter_stab = _stabilized_rate(batter_hr, batter_pa, league_hr, batter_prior_weight, "batter HR")
    pitcher_stab = _stabilized_rate(pitcher_hr, pitcher_bf, league_hr, pitcher_prior_weight, "pitcher HR allowed")
    if not 0.0 < batter_stab < 0.5 or not 0.0 < pitcher_stab < 0.5:
        raise HomeRunMatchupError("stabilized HR rates outside supported interval")

    # Symmetric batter/pitcher matchup on the probability scale.  The league rate is
    # explicit in diagnostics and stabilization; no hidden or proprietary weights.
    neutral_per_pa = sqrt(batter_stab * pitcher_stab)

    # Contact-quality fields are required to freeze provenance now, but they do not
    # alter the research probability until a PIT fit estimates their coefficients.
    _finite("barrel_rate", features.get("barrel_rate"), 0.0, 1.0)
    _finite("hard_hit_rate", features.get("hard_hit_rate"), 0.0, 1.0)
    _finite("avg_exit_velocity", features.get("avg_exit_velocity"), 50.0, 120.0)

    pa_pool = _pa_pool(features.get("pa_pool"))
    mean_pa = sum(pa_pool) / len(pa_pool)
    default_park = _finite("park_hr_factor", features.get("park_hr_factor"), 0.25, 4.0)
    default_weather = _finite("weather_hr_factor", features.get("weather_hr_factor"), 0.25, 4.0)
    scenarios = _environment_scenarios(model_input.get("shared_environment_scenarios"), default_park, default_weather)

    hr_probability = 0.0
    expected_hr = 0.0
    weighted_per_pa = 0.0
    for weight, park, weather in scenarios:
        per_pa = max(1e-8, min(0.5, neutral_per_pa * park * weather))
        scenario_no_hr = sum((1.0 - per_pa) ** pa for pa in pa_pool) / len(pa_pool)
        hr_probability += weight * (1.0 - scenario_no_hr)
        expected_hr += weight * mean_pa * per_pa
        weighted_per_pa += weight * per_pa

    digest = _canonical_hash(
        {
            "engine_version": ENGINE_VERSION,
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "build_hash": model_input.get("build_hash"),
            "lineup_status": lineup_status,
            "features": features,
            "shared_environment_scenarios": model_input.get("shared_environment_scenarios"),
            "source_hashes": source_hashes,
            "contact_quality_weighted": False,
        }
    )
    return HomeRunMatchupOutput(
        engine_version=ENGINE_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        model_input_hash=digest,
        batter_hr_rate_stabilized=batter_stab,
        pitcher_hr_rate_allowed_stabilized=pitcher_stab,
        neutral_per_pa_hr_probability=neutral_per_pa,
        per_pa_hr_probability=weighted_per_pa,
        expected_home_runs=expected_hr,
        home_run_probability=hr_probability,
        no_home_run_probability=1.0 - hr_probability,
        mean_plate_appearances=mean_pa,
        environment_scenario_count=len(scenarios),
        contact_quality_weighted=False,
    )
