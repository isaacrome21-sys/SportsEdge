"""PIT-checked research-only G1 handoff to the existing coherent NFL market engine.

G1 is not promoted. This adapter neither verifies fitted-model training lineage
nor changes frozen score-grid parameters or any live betting authority.
"""
from __future__ import annotations

from datetime import datetime
from math import isclose
from typing import Any, Mapping, Sequence

from sportsedge.sports.nfl.discrete_v2 import MEAN_CEILING, MEAN_FLOOR
from sportsedge.sports.nfl.location_symmetric_g1 import (
    CANDIDATE_FAMILY, MODEL_ID, NFLSymmetricLocationG1, team_means_from_location,
)
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, _assert_market_blind
from sportsedge.sports.nfl.unified_market_engine import (
    UnifiedNflModelError, run_unified_nfl_model,
)


def _aware(value: Any, field: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise UnifiedNflModelError(f"{field}:VALID_TIMESTAMP_REQUIRED") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise UnifiedNflModelError(f"{field}:TIMEZONE_REQUIRED")
    return result


def _reject_opaque_mappings(value: Any) -> None:
    """M2's market-blind guard only descends into real dict/list containers."""
    if isinstance(value, Mapping):
        if not isinstance(value, dict):
            raise UnifiedNflModelError("LOCATION_G1_OPAQUE_FEATURE_MAPPING_PROHIBITED")
        for child in value.values():
            _reject_opaque_mappings(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _reject_opaque_mappings(child)


def run_location_g1_research_market_bridge(
    *,
    model: NFLSymmetricLocationG1,
    game_features: Mapping[str, Any],
    observed_at: str,
    game_start_ts: str,
    game_id: str,
    home_team: str,
    away_team: str,
    game_markets: Sequence[Mapping[str, Any]] = (),
    prop_markets: Sequence[Mapping[str, Any]] = (),
    home_model: Mapping[str, Any] | None = None,
    away_model: Mapping[str, Any] | None = None,
    scoring_prior: Any | None = None,
    n_sims: int = 20000,
    seed: int = 21,
) -> dict[str, Any]:
    """Price research game and player markets using one seeded score simulation.

    No historical row provenance or prospective betting authority is asserted.
    Kickoff is explicit: canonical M2 feature rows omit the kickoff timestamp.
    """
    if not isinstance(model, NFLSymmetricLocationG1):
        raise UnifiedNflModelError("LOCATION_G1_FITTED_MODEL_REQUIRED")
    if (
        model.model_id != MODEL_ID
        or model.candidate_family != CANDIDATE_FAMILY
        or model.feature_contract != NFL_M2_FEATURE_CONTRACT
    ):
        raise UnifiedNflModelError("LOCATION_G1_MODEL_CONTRACT_MISMATCH")
    if not isinstance(game_features, dict):
        raise UnifiedNflModelError("LOCATION_G1_GAME_FEATURES_DICT_REQUIRED")
    _reject_opaque_mappings(game_features)
    _assert_market_blind(game_features, path="location_g1_game_features")

    observed = _aware(observed_at, "LOCATION_G1_OBSERVED_AT")
    kickoff = _aware(game_start_ts, "LOCATION_G1_GAME_START")
    if observed >= kickoff:
        raise UnifiedNflModelError("LOCATION_G1_OBSERVATION_NOT_PREGAME")
    if game_features.get("game_id") not in (None, game_id):
        raise UnifiedNflModelError("LOCATION_G1_GAME_ID_MISMATCH")
    if game_features.get("game_start_ts") is not None:
        if _aware(game_features["game_start_ts"], "LOCATION_G1_GAME_START") != kickoff:
            raise UnifiedNflModelError("LOCATION_G1_GAME_START_MISMATCH")

    for side in ("home", "away"):
        features = game_features.get(f"{side}_features")
        if not isinstance(features, dict):
            raise UnifiedNflModelError(f"LOCATION_G1_{side.upper()}_FEATURES_DICT_REQUIRED")
        if features.get("feature_contract") != NFL_M2_FEATURE_CONTRACT:
            raise UnifiedNflModelError(f"LOCATION_G1_{side.upper()}_FEATURE_CONTRACT_MISMATCH")
        asof = _aware(features.get("feature_asof_ts"), f"LOCATION_G1_{side.upper()}_FEATURE_ASOF")
        if asof > observed:
            raise UnifiedNflModelError(f"LOCATION_G1_{side.upper()}_PIT_WINDOW_INVALID")
        if features.get("game_start_ts") is not None:
            if _aware(features["game_start_ts"], f"LOCATION_G1_{side.upper()}_GAME_START") != kickoff:
                raise UnifiedNflModelError("LOCATION_G1_GAME_START_MISMATCH")

    margin, total = model.predict(game_features)
    means = team_means_from_location(margin, total)
    if any(not MEAN_FLOOR <= mean <= MEAN_CEILING for mean in means.values()):
        raise UnifiedNflModelError("LOCATION_G1_OUTSIDE_FROZEN_GRID_MEAN_BOUNDS")

    out = run_unified_nfl_model(
        game_id=game_id, home_team=home_team, away_team=away_team,
        attempt9_margin=margin, attempt9_total=total,
        game_markets=game_markets, prop_markets=prop_markets,
        home_model=home_model, away_model=away_model,
        scoring_prior=scoring_prior, n_sims=n_sims, seed=seed,
    )
    if any(
        not isclose(float(out["score_means"][key]), expected, rel_tol=0.0, abs_tol=1e-10)
        for key, expected in means.items()
    ):
        raise UnifiedNflModelError("LOCATION_G1_GRID_MEANS_CHANGED")
    out["attempt9_raw"] = None
    out["location_g1_raw"] = {
        "margin": margin, "total": total,
        "model_id": model.model_id, "candidate_family": model.candidate_family,
        "feature_contract": model.feature_contract,
        "observed_at": observed.isoformat(), "game_start_ts": kickoff.isoformat(),
        "training_lineage_verified": False,
    }
    out["score_distribution"]["location_source"] = "LOCATION_SYMMETRIC_G1_RESEARCH"
    out["authority"].update({
        "research_only": True, "creates_model_p": False,
        "official_authority": False, "promotion_authority": False,
        "staking_authority": False,
    })
    return out


__all__ = ["run_location_g1_research_market_bridge"]
