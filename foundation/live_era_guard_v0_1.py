#!/usr/bin/env python3
"""Fail-closed guard for using historical/season-keyed model artifacts in a later live era.

This does not invent a 2026 model-selection rule. It detects when an artifact is
keyed by scoring season and refuses to authorize a target season newer than the
latest represented scoring season unless an explicit, separately verified live-
era policy attestation is supplied.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Set


class LiveEraError(RuntimeError):
    pass


def scoring_seasons_from_model_keys(keys: Iterable[str]) -> Set[int]:
    seasons: Set[int] = set()
    for key in keys:
        if not isinstance(key, str) or "|" not in key:
            raise LiveEraError(f"UNPARSEABLE_MODEL_KEY:{key!r}")
        season_text = key.split("|", 1)[0]
        try:
            season = int(season_text)
        except Exception as exc:
            raise LiveEraError(f"UNPARSEABLE_MODEL_SEASON:{key!r}") from exc
        seasons.add(season)
    if not seasons:
        raise LiveEraError("NO_SCORING_SEASONS")
    return seasons


def season_keyed_artifact_status(
    *,
    market: str,
    artifact: Dict[str, Any],
    target_season: int,
    live_era_attestation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    models = artifact.get("models")
    if not isinstance(models, dict):
        return {"market": market, "status": "BLOCKED", "reason": "ARTIFACT_MODELS_MISSING"}
    try:
        seasons = scoring_seasons_from_model_keys(models.keys())
    except LiveEraError as exc:
        return {"market": market, "status": "BLOCKED", "reason": str(exc)}

    latest = max(seasons)
    if target_season in seasons:
        return {
            "market": market,
            "status": "PASS_HISTORICAL_SEASON_KEY_PRESENT",
            "target_season": target_season,
            "available_scoring_seasons": sorted(seasons),
            "selected_season": target_season,
        }

    if target_season < min(seasons):
        return {
            "market": market,
            "status": "BLOCKED",
            "reason": "TARGET_SEASON_PRECEDES_ARTIFACT_SCORING_RANGE",
            "target_season": target_season,
            "available_scoring_seasons": sorted(seasons),
        }

    # Critical case: live season is newer than every validated scoring key.
    att = live_era_attestation or {}
    required = {
        "market": market,
        "target_season": target_season,
        "artifact_latest_scoring_season": latest,
        "policy_verified": True,
    }
    if not all(att.get(k) == v for k, v in required.items()):
        return {
            "market": market,
            "status": "BLOCKED_LIVE_ERA_POLICY",
            "reason": "NO_VERIFIED_MODEL_SELECTION_POLICY_FOR_NEWER_SEASON",
            "target_season": target_season,
            "available_scoring_seasons": sorted(seasons),
            "latest_scoring_season": latest,
        }

    policy = att.get("policy")
    validation_hash = att.get("validation_hash")
    if not isinstance(policy, str) or not policy or not isinstance(validation_hash, str) or not validation_hash:
        return {
            "market": market,
            "status": "BLOCKED_LIVE_ERA_POLICY",
            "reason": "LIVE_ERA_ATTESTATION_INCOMPLETE",
            "target_season": target_season,
            "latest_scoring_season": latest,
        }

    return {
        "market": market,
        "status": "PASS_LIVE_ERA_POLICY_ATTESTED",
        "target_season": target_season,
        "available_scoring_seasons": sorted(seasons),
        "latest_scoring_season": latest,
        "policy": policy,
        "validation_hash": validation_hash,
    }
