"""Per-card shared engine session for the derived F5 markets.

Mirrors sportsedge.shared_f5_engine: one session per card run, the
underlying F5 distribution is the pinned production construction
(same builder, same stochastic identity, so its distribution SHA is
identical to the one the F5 session produces for the same features),
cached by input hash. The difference is only the read-out layer:
sportsedge.f5_derived_readouts for F5_BOTH_TEAMS_TO_SCORE,
F5_WINNING_MARGIN and F5_CORRECT_SCORE. Readouts are returned as
provenance (model_p plus distribution/readout hashes); the binding
layer consumes only the hashes as a reachability proof. push_p is
exactly 0.0: no derived selection pushes.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .f5_derived_readouts import (
    F5_BTTS_MARKET,
    F5_CORRECT_SCORE_MARKET,
    F5_DERIVED_MARKETS,
    F5_WINNING_MARGIN_MARKET,
    read_f5_btts_probability,
    read_f5_correct_score_probability,
    read_f5_winning_margin_probability,
    readout_version,
)
from .f5_distribution import (
    F5_DISTRIBUTION_VERSION,
    LEAGUE_PRIOR_STRENGTH,
    F5Distribution,
    build_f5_distribution,
)
from .source_lineage import canonical_json_sha256


class SharedF5DerivedEngineError(ValueError):
    pass


def _production_builder(features: Mapping[str, Any]) -> F5Distribution:
    return build_f5_distribution(
        features,
        league_prior_strength=LEAGUE_PRIOR_STRENGTH,
    )


def build_shared_f5_derived_engine_session(
    *,
    builder: Callable[[Mapping[str, Any]], F5Distribution] | None = None,
) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    if builder is None:
        builder = _production_builder
    cache: dict[str, F5Distribution] = {}

    def engine(model_input: Mapping[str, Any]) -> dict[str, Any]:
        market = str(model_input.get("market", "")).upper()
        if market not in F5_DERIVED_MARKETS:
            raise SharedF5DerivedEngineError(
                f"unsupported derived F5 market: {market}")
        game_id = str(model_input.get("game_id", "")).strip()
        if not game_id:
            raise SharedF5DerivedEngineError("game_id required")
        features = model_input.get("features")
        if not isinstance(features, Mapping):
            raise SharedF5DerivedEngineError("F5 features required")
        feature_source_hash = str(model_input.get("feature_source_hash") or "").strip()
        if not feature_source_hash:
            raise SharedF5DerivedEngineError("feature_source_hash required")

        # Identical stochastic identity to the F5 session: the derived
        # markets read the SAME joint score state, so the distribution
        # SHA matches the F5 session's for the same features.
        stochastic_identity = {
            "engine": F5_DISTRIBUTION_VERSION,
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

        side = str(model_input.get("side", ""))
        if market == F5_BTTS_MARKET:
            readout = read_f5_btts_probability(
                distribution, line=model_input.get("line"), side=side)
        elif market == F5_WINNING_MARGIN_MARKET:
            readout = read_f5_winning_margin_probability(
                distribution,
                partition=model_input.get("partition") or (),
                selection=side)
        else:  # F5_CORRECT_SCORE_MARKET
            readout = read_f5_correct_score_probability(
                distribution,
                partition=model_input.get("partition") or (),
                selection=side)
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
            "engine_version": readout_version(),
            "seed_policy": "analytic_empirical_f5_state_m30_league_prior_derived_readouts",
            "mc_paths": 0,
        }

    return engine
