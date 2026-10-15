"""Per-card shared engine session for MLB first-3 / first-7 markets.

Mirrors sportsedge.shared_f5_engine: one session per period (3 or 7
innings), distributions cached by input hash, readouts returned as
provenance (model_p/push_p plus distribution/readout hashes). The
binding layer consumes only the hashes as a reachability proof; no
probability from this session is a card price.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .period_distribution import (
    LEAGUE_PRIOR_STRENGTH,
    PeriodDistribution,
    build_period_distribution,
    distribution_version,
    period_markets,
    read_period_probability,
)
from .source_lineage import canonical_json_sha256


class SharedPeriodEngineError(ValueError):
    pass


def _production_builder(innings: int) -> Callable[[Mapping[str, Any]], PeriodDistribution]:
    def builder(features: Mapping[str, Any]) -> PeriodDistribution:
        return build_period_distribution(
            features,
            innings=innings,
            league_prior_strength=LEAGUE_PRIOR_STRENGTH,
        )
    return builder


def build_shared_period_engine_session(
    *,
    innings: int,
    builder: Callable[[Mapping[str, Any]], PeriodDistribution] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    markets = period_markets(innings)
    if builder is None:
        builder = _production_builder(innings)
    cache: dict[str, PeriodDistribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        market = str(model_input.get("market", "")).upper()
        if market not in markets:
            raise SharedPeriodEngineError(
                f"unsupported F{innings} period market: {market}")
        game_id = str(model_input.get("game_id", "")).strip()
        if not game_id:
            raise SharedPeriodEngineError("game_id required")
        features = model_input.get("features")
        if not isinstance(features, Mapping):
            raise SharedPeriodEngineError("period features required")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not feature_source_hash:
            raise SharedPeriodEngineError("feature_source_hash required")

        stochastic_identity = {
            "engine": distribution_version(innings),
            "game_id": game_id,
            "feature_source_hash": feature_source_hash,
            "features": dict(features),
            "league_prior_strength": LEAGUE_PRIOR_STRENGTH,
        }
        model_input_hash = canonical_json_sha256(stochastic_identity)
        distribution = cache.get(model_input_hash)
        if distribution is None:
            distribution = builder(features)
            cache[model_input_hash] = distribution

        readout = read_period_probability(
            distribution,
            market=market,
            line=model_input.get("line"),
            side=str(model_input.get("side", "")),
            team_side=model_input.get("team_side"),
        )
        return {
            "game_id": model_input.get("game_id"),
            "market": model_input.get("market"),
            "entity_id": model_input.get("entity_id"),
            "line": model_input.get("line"),
            "side": model_input.get("side"),
            "model_p": readout.probability,
            "push_p": readout.push_probability,
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution.distribution_sha256,
            "readout_sha256": readout.readout_sha256,
            "readout_version": readout.readout_version,
            "engine_version": distribution_version(innings),
            "seed_policy": f"analytic_empirical_period_state_m30_league_prior_f{innings}",
            "mc_paths": 0,
        }

    return engine
