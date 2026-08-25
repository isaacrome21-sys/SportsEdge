"""Per-card shared engine session for first-five MLB markets."""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .f5_distribution import (
    F5_DISTRIBUTION_VERSION,
    F5_MARKETS,
    F5Distribution,
    build_f5_distribution,
    read_f5_probability,
)
from .source_lineage import canonical_json_sha256

STAGE1_F5_MARKETS = F5_MARKETS


class SharedF5EngineError(ValueError):
    pass


def build_shared_f5_engine_session(
    *,
    builder: Callable[[Mapping[str, Any]], F5Distribution] = build_f5_distribution,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    cache: dict[str, F5Distribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        market = str(model_input.get("market", "")).upper()
        if market not in STAGE1_F5_MARKETS:
            raise SharedF5EngineError(f"unsupported Stage 1 F5 market: {market}")
        game_id = str(model_input.get("game_id", "")).strip()
        if not game_id:
            raise SharedF5EngineError("game_id required")
        features = model_input.get("features")
        if not isinstance(features, Mapping):
            raise SharedF5EngineError("F5 features required")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not feature_source_hash:
            raise SharedF5EngineError("feature_source_hash required")

        stochastic_identity = {
            "engine": F5_DISTRIBUTION_VERSION,
            "game_id": game_id,
            "feature_source_hash": feature_source_hash,
            "features": dict(features),
        }
        model_input_hash = canonical_json_sha256(stochastic_identity)
        distribution = cache.get(model_input_hash)
        if distribution is None:
            distribution = builder(features)
            cache[model_input_hash] = distribution

        readout = read_f5_probability(
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
            "engine_version": F5_DISTRIBUTION_VERSION,
            "seed_policy": "analytic_empirical_f5_state",
            "mc_paths": 0,
        }

    return engine
