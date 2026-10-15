"""Per-card shared engine session for the MLB Total Runs 3-Way market.

Mirrors sportsedge.shared_period_engine: one session per card run,
distributions cached by input hash, readouts returned as provenance
(model_p / exactly_p / push_p plus distribution/readout hashes). The
binding layer consumes only the hashes as a reachability proof; no
probability from this session is a card price. push_p is exactly 0.0
by construction: a 3-way selection never pushes -- the line cell is
the EXACTLY selection's win, reported separately as exactly_p.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .game_total_distribution import (
    GAME_TOTAL_3WAY_MARKET,
    LEAGUE_PRIOR_STRENGTH,
    GameTotalDistribution,
    build_game_total_distribution,
    distribution_version,
    read_game_total_probability,
)
from .source_lineage import canonical_json_sha256


class SharedGameTotalEngineError(ValueError):
    pass


def _production_builder(features: Mapping[str, Any]) -> GameTotalDistribution:
    return build_game_total_distribution(
        features,
        league_prior_strength=LEAGUE_PRIOR_STRENGTH,
    )


def build_shared_game_total_engine_session(
    *,
    builder: Callable[[Mapping[str, Any]], GameTotalDistribution] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    if builder is None:
        builder = _production_builder
    cache: dict[str, GameTotalDistribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        market = str(model_input.get("market", "")).upper()
        if market != GAME_TOTAL_3WAY_MARKET:
            raise SharedGameTotalEngineError(
                f"unsupported game total market: {market}")
        game_id = str(model_input.get("game_id", "")).strip()
        if not game_id:
            raise SharedGameTotalEngineError("game_id required")
        features = model_input.get("features")
        if not isinstance(features, Mapping):
            raise SharedGameTotalEngineError("game total features required")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not feature_source_hash:
            raise SharedGameTotalEngineError("feature_source_hash required")

        stochastic_identity = {
            "engine": distribution_version(),
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

        readout = read_game_total_probability(
            distribution,
            market=market,
            line=model_input.get("line"),
            side=str(model_input.get("side", "")),
        )
        return {
            "game_id": model_input.get("game_id"),
            "market": model_input.get("market"),
            "entity_id": model_input.get("entity_id"),
            "line": model_input.get("line"),
            "side": model_input.get("side"),
            "model_p": readout.probability,
            "exactly_p": readout.exactly_probability,
            "push_p": readout.push_probability,
            "model_input_hash": model_input_hash,
            "distribution_sha256": distribution.distribution_sha256,
            "readout_sha256": readout.readout_sha256,
            "readout_version": readout.readout_version,
            "engine_version": distribution_version(),
            "seed_policy": "analytic_empirical_game_total_state_m30_league_prior_full_game",
            "mc_paths": 0,
        }

    return engine
