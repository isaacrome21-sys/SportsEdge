"""Research-only MLB NRFI/YRFI matchup challenger.

This module is deliberately isolated from production registration.  It creates a
price-independent pregame probability candidate from point-in-time baseball inputs,
with additive small-sample stabilization and explicit coefficient inputs.  Merely
running this code does not create Model_P, Truth Gate passage, promotion, staking,
or OFFICIAL authority.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from math import exp, isfinite, log
from typing import Any, Mapping, Sequence

ENGINE_VERSION = "mlb_first_inning_research_v0.1"
FEATURE_CONTRACT_VERSION = "mlb_first_inning_pitcher_top3_environment_v1"


class FirstInningResearchError(ValueError):
    """Raised when a research input fails the fail-closed contract."""


@dataclass(frozen=True)
class FirstInningOutput:
    engine_version: str
    feature_contract_version: str
    model_input_hash: str
    nrfi_probability: float
    yrfi_probability: float
    away_batting_yrfi_probability: float
    home_batting_yrfi_probability: float
    away_pitcher_scoreless_stabilized: float
    home_pitcher_scoreless_stabilized: float
    away_top3_obp_stabilized: float
    home_top3_obp_stabilized: float
    environment_scenario_count: int


def _finite(name: str, value: Any, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(value, bool):
        raise FirstInningResearchError(f"invalid {name}")
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FirstInningResearchError(f"invalid {name}") from exc
    if not isfinite(out) or (lo is not None and out < lo) or (hi is not None and out > hi):
        raise FirstInningResearchError(f"invalid {name}")
    return out


def _count(name: str, value: Any, lo: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < lo:
        raise FirstInningResearchError(f"invalid {name}")
    return value


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _source_hashes(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise FirstInningResearchError("source_hashes must be a non-empty mapping")
    out: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        digest = str(raw_value).strip()
        if not key or not digest:
            raise FirstInningResearchError("source_hashes keys and values must be non-empty")
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
            raise FirstInningResearchError(f"sportsbook-derived feature banned: {key}")


def _stabilized_rate(successes: int, trials: int, prior_mean: float, prior_weight: float, name: str) -> float:
    if successes > trials:
        raise FirstInningResearchError(f"{name} successes exceed trials")
    if trials == 0 and prior_weight == 0:
        raise FirstInningResearchError(f"{name} has no observations or prior weight")
    return (successes + prior_mean * prior_weight) / (trials + prior_weight)


def _coefficients(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise FirstInningResearchError("coefficients must be a mapping")
    bounds = {
        "intercept": (-5.0, 2.0),
        "beta_pitcher_exit": (-4.0, 4.0),
        "beta_top3_obp": (-10.0, 10.0),
        "beta_park": (-3.0, 3.0),
        "beta_weather": (-3.0, 3.0),
    }
    out: dict[str, float] = {}
    for name, (lo, hi) in bounds.items():
        if name not in value:
            raise FirstInningResearchError(f"missing coefficient: {name}")
        out[name] = _finite(name, value[name], lo, hi)
    extra = set(value) - set(bounds)
    if extra:
        raise FirstInningResearchError(f"unexpected coefficients: {sorted(str(x) for x in extra)}")
    return out


def _side_probability(
    *,
    pitcher_scoreless: float,
    top3_obp: float,
    league_pitcher_scoreless: float,
    league_top3_obp: float,
    park_run_factor: float,
    weather_run_factor: float,
    coeffs: Mapping[str, float],
) -> float:
    # All terms are relative to league context so a neutral matchup remains anchored
    # to the fitted intercept.  Coefficients are supplied by the caller/future PIT
    # artifact; this research module does not invent or copy proprietary weights.
    pitcher_exit = log((1.0 - pitcher_scoreless) / (1.0 - league_pitcher_scoreless))
    top3_term = log(top3_obp / league_top3_obp)
    linear = (
        coeffs["intercept"]
        + coeffs["beta_pitcher_exit"] * pitcher_exit
        + coeffs["beta_top3_obp"] * top3_term
        + coeffs["beta_park"] * log(park_run_factor)
        + coeffs["beta_weather"] * log(weather_run_factor)
    )
    run_lambda = max(1e-10, min(4.0, exp(linear)))
    return 1.0 - exp(-run_lambda)


def _environment_scenarios(
    raw: Any,
    default_park: float,
    default_weather: float,
) -> list[tuple[float, float, float]]:
    if raw is None:
        return [(1.0, default_park, default_weather)]
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise FirstInningResearchError("shared_environment_scenarios must be a non-empty sequence")
    parsed: list[tuple[float, float, float]] = []
    weight_sum = 0.0
    for idx, item in enumerate(raw):
        if not isinstance(item, Mapping):
            raise FirstInningResearchError(f"environment scenario {idx} must be a mapping")
        weight = _finite(f"scenario[{idx}].weight", item.get("weight"), 1e-12)
        park = _finite(f"scenario[{idx}].park_run_factor", item.get("park_run_factor"), 0.25, 4.0)
        weather = _finite(f"scenario[{idx}].weather_run_factor", item.get("weather_run_factor"), 0.25, 4.0)
        parsed.append((weight, park, weather))
        weight_sum += weight
    return [(weight / weight_sum, park, weather) for weight, park, weather in parsed]


def simulate_first_inning(model_input: Mapping[str, Any]) -> FirstInningOutput:
    if not isinstance(model_input, Mapping):
        raise FirstInningResearchError("model_input must be a mapping")
    if model_input.get("market") not in {"nrfi", "yrfi", "nrfi_yrfi"}:
        raise FirstInningResearchError("wrong market for MLB first-inning challenger")
    if model_input.get("game_status") != "PRE_GAME":
        raise FirstInningResearchError("first-inning challenger is pregame only")
    if model_input.get("confirmed_starters") is not True:
        raise FirstInningResearchError("confirmed starters required")
    if model_input.get("confirmed_top_orders") is not True:
        raise FirstInningResearchError("confirmed top orders required")
    if not model_input.get("build_hash"):
        raise FirstInningResearchError("missing build_hash")

    features = model_input.get("features")
    if not isinstance(features, Mapping):
        raise FirstInningResearchError("features must be a mapping")
    _reject_book_features(features)
    source_hashes = _source_hashes(model_input.get("source_hashes"))
    coeffs = _coefficients(model_input.get("coefficients"))

    league_pitcher_scoreless = _finite(
        "league_pitcher_scoreless_first_rate", features.get("league_pitcher_scoreless_first_rate"), 1e-6, 1.0 - 1e-6
    )
    league_top3_obp = _finite("league_top3_obp", features.get("league_top3_obp"), 1e-6, 1.0 - 1e-6)
    pitcher_prior_weight = _finite("pitcher_prior_weight", features.get("pitcher_prior_weight"), 0.0, 500.0)
    top3_prior_weight = _finite("top3_prior_weight", features.get("top3_prior_weight"), 0.0, 5000.0)

    away_pitcher_starts = _count("away_pitcher_first_inning_starts", features.get("away_pitcher_first_inning_starts"))
    away_pitcher_scoreless = _count("away_pitcher_scoreless_firsts", features.get("away_pitcher_scoreless_firsts"))
    home_pitcher_starts = _count("home_pitcher_first_inning_starts", features.get("home_pitcher_first_inning_starts"))
    home_pitcher_scoreless = _count("home_pitcher_scoreless_firsts", features.get("home_pitcher_scoreless_firsts"))

    away_top3_pa = _count("away_top3_pa", features.get("away_top3_pa"))
    away_top3_on_base = _count("away_top3_times_on_base", features.get("away_top3_times_on_base"))
    home_top3_pa = _count("home_top3_pa", features.get("home_top3_pa"))
    home_top3_on_base = _count("home_top3_times_on_base", features.get("home_top3_times_on_base"))

    away_pitcher_stab = _stabilized_rate(
        away_pitcher_scoreless, away_pitcher_starts, league_pitcher_scoreless, pitcher_prior_weight, "away pitcher"
    )
    home_pitcher_stab = _stabilized_rate(
        home_pitcher_scoreless, home_pitcher_starts, league_pitcher_scoreless, pitcher_prior_weight, "home pitcher"
    )
    away_top3_stab = _stabilized_rate(away_top3_on_base, away_top3_pa, league_top3_obp, top3_prior_weight, "away top3")
    home_top3_stab = _stabilized_rate(home_top3_on_base, home_top3_pa, league_top3_obp, top3_prior_weight, "home top3")

    # Avoid undefined log ratios at exact 0/1 after stabilization.
    for name, value in {
        "away_pitcher_stabilized": away_pitcher_stab,
        "home_pitcher_stabilized": home_pitcher_stab,
        "away_top3_stabilized": away_top3_stab,
        "home_top3_stabilized": home_top3_stab,
    }.items():
        if not 1e-8 < value < 1.0 - 1e-8:
            raise FirstInningResearchError(f"{name} outside open probability interval")

    default_park = _finite("park_run_factor", features.get("park_run_factor"), 0.25, 4.0)
    default_weather = _finite("weather_run_factor", features.get("weather_run_factor"), 0.25, 4.0)
    scenarios = _environment_scenarios(model_input.get("shared_environment_scenarios"), default_park, default_weather)

    nrfi = 0.0
    away_bat_yrfi = 0.0
    home_bat_yrfi = 0.0
    for weight, park, weather in scenarios:
        # Away hitters face the home starter; home hitters face the away starter.
        away_score = _side_probability(
            pitcher_scoreless=home_pitcher_stab,
            top3_obp=away_top3_stab,
            league_pitcher_scoreless=league_pitcher_scoreless,
            league_top3_obp=league_top3_obp,
            park_run_factor=park,
            weather_run_factor=weather,
            coeffs=coeffs,
        )
        home_score = _side_probability(
            pitcher_scoreless=away_pitcher_stab,
            top3_obp=home_top3_stab,
            league_pitcher_scoreless=league_pitcher_scoreless,
            league_top3_obp=league_top3_obp,
            park_run_factor=park,
            weather_run_factor=weather,
            coeffs=coeffs,
        )
        nrfi += weight * (1.0 - away_score) * (1.0 - home_score)
        away_bat_yrfi += weight * away_score
        home_bat_yrfi += weight * home_score

    yrfi = 1.0 - nrfi
    digest = _canonical_hash(
        {
            "engine_version": ENGINE_VERSION,
            "feature_contract_version": FEATURE_CONTRACT_VERSION,
            "build_hash": model_input.get("build_hash"),
            "features": features,
            "coefficients": coeffs,
            "shared_environment_scenarios": model_input.get("shared_environment_scenarios"),
            "source_hashes": source_hashes,
        }
    )
    return FirstInningOutput(
        engine_version=ENGINE_VERSION,
        feature_contract_version=FEATURE_CONTRACT_VERSION,
        model_input_hash=digest,
        nrfi_probability=nrfi,
        yrfi_probability=yrfi,
        away_batting_yrfi_probability=away_bat_yrfi,
        home_batting_yrfi_probability=home_bat_yrfi,
        away_pitcher_scoreless_stabilized=away_pitcher_stab,
        home_pitcher_scoreless_stabilized=home_pitcher_stab,
        away_top3_obp_stabilized=away_top3_stab,
        home_top3_obp_stabilized=home_top3_stab,
        environment_scenario_count=len(scenarios),
    )
