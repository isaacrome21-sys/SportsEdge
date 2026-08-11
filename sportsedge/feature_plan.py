"""Resolve declarative live feature plans into versioned feature rows."""
from __future__ import annotations

from typing import Any, Mapping

from .feature_bridge import FeatureBridgeError, resolve_feature_row


class FeaturePlanError(ValueError):
    pass


def resolve_feature_plan(
    plan: Any,
    *,
    sources: Any,
    now,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve every requested feature target; preserve failures explicitly.

    A plan row contains market/game_pk/player_id/team_id/wager_cutoff,
    feature_fact_keys, and ttl_by_feature. Failed rows are returned separately
    rather than silently dropped.
    """
    if not isinstance(plan, list):
        raise FeaturePlanError("feature plan must be a JSON list")
    if not isinstance(sources, list):
        raise FeaturePlanError("sources must be a JSON list")

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for i, raw in enumerate(plan):
        if not isinstance(raw, Mapping):
            raise FeaturePlanError(f"feature plan row {i} must be an object")
        try:
            market = str(raw["market"])
            game_pk = int(raw["game_pk"])
            player_id = int(raw["player_id"])
            team_id = int(raw["team_id"])
            wager_cutoff = raw["wager_cutoff"]
            feature_fact_keys = raw["feature_fact_keys"]
            ttl_by_feature = raw["ttl_by_feature"]
        except Exception as exc:
            raise FeaturePlanError(f"feature plan row {i} missing/invalid identity") from exc

        key = (str(game_pk), str(player_id), market)
        if key in seen:
            failures.append({
                "game_pk": game_pk, "player_id": player_id, "market": market,
                "reason": "DUPLICATE_PLAN_TARGET", "detail": {},
            })
            continue
        seen.add(key)

        try:
            row = resolve_feature_row(
                market=market,
                game_pk=game_pk,
                player_id=player_id,
                team_id=team_id,
                feature_fact_keys=feature_fact_keys,
                sources=sources,
                ttl_by_feature=ttl_by_feature,
                now=now,
                wager_cutoff=wager_cutoff,
            )
            rows.append(row)
        except FeatureBridgeError as exc:
            failures.append({
                "game_pk": game_pk, "player_id": player_id, "market": market,
                "reason": exc.reason, "detail": exc.detail,
            })

    return rows, failures
