"""Research-only CFB game-state player opportunity allocator.

This module consumes a market-blind CFB participation/substitution artifact plus
pregame baseline player usage shares. It adjusts starter exposure for realized
game state and redistributes vacated opportunity to declared non-starters within
the same position group.

The allocator is deliberately non-authoritative. It cannot activate the CFB
player-prop surface, create Model_P, promote a market, or grant OFFICIAL status.
"""
from __future__ import annotations

from hashlib import sha256
import json
from math import isfinite
from typing import Any, Iterable, Mapping

from .prop_participation_model import (
    CFBParticipationModelError,
    starter_retention_probability,
    validate_cfb_participation_artifact,
)

SCHEMA_VERSION = "CFB_PROP_STATE_ALLOCATOR_V1"
_METRICS = ("rush_share", "target_share", "red_zone_share")
_ALLOWED_PLAYER_FIELDS = frozenset(
    {
        "player_id",
        "position_group",
        "starter",
        "baseline_rush_share",
        "baseline_target_share",
        "baseline_red_zone_share",
        "source_sha256",
    }
)
_EPS = 1e-12


class CFBPropStateAllocatorError(ValueError):
    pass


def _canonical_sha256(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(raw).hexdigest()


def _finite(value: Any, code: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise CFBPropStateAllocatorError(code) from exc
    if not isfinite(out):
        raise CFBPropStateAllocatorError(code)
    return out


def _share(value: Any, code: str) -> float:
    out = _finite(value, code)
    if out < 0.0 or out > 1.0:
        raise CFBPropStateAllocatorError(code)
    return out


def _hex64(value: Any, code: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise CFBPropStateAllocatorError(code)
    return text


def _normalize_player(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_PLAYER_INVALID")
    unknown = set(raw) - _ALLOWED_PLAYER_FIELDS
    if unknown:
        raise CFBPropStateAllocatorError(
            "CFB_PROP_STATE_PLAYER_FIELD_FORBIDDEN:"
            + ",".join(sorted(str(value) for value in unknown))
        )
    missing = _ALLOWED_PLAYER_FIELDS - set(raw)
    if missing:
        raise CFBPropStateAllocatorError(
            "CFB_PROP_STATE_PLAYER_FIELD_REQUIRED:"
            + ",".join(sorted(str(value) for value in missing))
        )

    player_id = str(raw.get("player_id") or "").strip()
    if not player_id:
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_PLAYER_ID_REQUIRED")
    position_group = str(raw.get("position_group") or "").strip().upper()
    if position_group not in {"QB", "RB", "WR", "TE", "OTHER"}:
        raise CFBPropStateAllocatorError(
            f"CFB_PROP_STATE_POSITION_GROUP_INVALID:{position_group}"
        )
    starter = raw.get("starter")
    if type(starter) is not bool:
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_STARTER_BOOL_REQUIRED")

    return {
        "player_id": player_id,
        "position_group": position_group,
        "starter": starter,
        "rush_share": _share(
            raw.get("baseline_rush_share"),
            "CFB_PROP_STATE_BASELINE_RUSH_SHARE_INVALID",
        ),
        "target_share": _share(
            raw.get("baseline_target_share"),
            "CFB_PROP_STATE_BASELINE_TARGET_SHARE_INVALID",
        ),
        "red_zone_share": _share(
            raw.get("baseline_red_zone_share"),
            "CFB_PROP_STATE_BASELINE_RED_ZONE_SHARE_INVALID",
        ),
        "source_sha256": _hex64(
            raw.get("source_sha256"), "CFB_PROP_STATE_SOURCE_SHA256_INVALID"
        ),
    }


def _validate_state(
    *,
    quarter: int,
    clock_seconds_remaining: int,
    score_margin: float,
    yards_to_endzone: float,
) -> dict[str, Any]:
    if isinstance(quarter, bool) or not isinstance(quarter, int) or quarter not in (1, 2, 3, 4):
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_QUARTER_INVALID")
    if (
        isinstance(clock_seconds_remaining, bool)
        or not isinstance(clock_seconds_remaining, int)
        or not 0 <= clock_seconds_remaining <= 900
    ):
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_CLOCK_INVALID")
    margin = _finite(score_margin, "CFB_PROP_STATE_SCORE_MARGIN_INVALID")
    yte = _finite(yards_to_endzone, "CFB_PROP_STATE_YARDS_TO_ENDZONE_INVALID")
    if yte < 0.0 or yte > 100.0:
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_YARDS_TO_ENDZONE_INVALID")
    return {
        "quarter": quarter,
        "clock_seconds_remaining": clock_seconds_remaining,
        "score_margin": margin,
        "yards_to_endzone": yte,
        "red_zone_active": yte <= 20.0,
    }


def _group_totals(players: list[dict[str, Any]], group: str) -> dict[str, float]:
    subset = [row for row in players if row["position_group"] == group]
    return {
        metric: float(sum(row[metric] for row in subset))
        for metric in _METRICS
    }


def allocate_cfb_player_opportunity(
    participation_artifact: Mapping[str, Any],
    players: Iterable[Mapping[str, Any]],
    *,
    quarter: int,
    clock_seconds_remaining: int,
    score_margin: float,
    yards_to_endzone: float,
) -> dict[str, Any]:
    """Adjust baseline player opportunity shares for CFB substitution state.

    Starter opportunity in each modeled position group is multiplied by the
    fitted starter-retention probability. Vacated mass is redistributed only to
    declared non-starters in that same group and same metric, in proportion to
    their baseline shares. Metric mass is conserved exactly within tolerance.
    """
    try:
        artifact = validate_cfb_participation_artifact(participation_artifact)
    except CFBParticipationModelError as exc:
        raise CFBPropStateAllocatorError(
            f"CFB_PROP_STATE_PARTICIPATION_ARTIFACT_INVALID:{exc}"
        ) from exc

    state = _validate_state(
        quarter=quarter,
        clock_seconds_remaining=clock_seconds_remaining,
        score_margin=score_margin,
        yards_to_endzone=yards_to_endzone,
    )
    normalized = [_normalize_player(row) for row in players]
    if not normalized:
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_PLAYERS_EMPTY")
    ids = [row["player_id"] for row in normalized]
    if len(ids) != len(set(ids)):
        raise CFBPropStateAllocatorError("CFB_PROP_STATE_PLAYER_ID_DUPLICATE")

    groups = sorted({row["position_group"] for row in normalized})
    adjusted = [dict(row) for row in normalized]
    retention_by_group: dict[str, float] = {}

    for group in groups:
        indices = [
            index for index, row in enumerate(normalized)
            if row["position_group"] == group
        ]
        if not any(normalized[index]["starter"] for index in indices):
            raise CFBPropStateAllocatorError(
                f"CFB_PROP_STATE_STARTER_REQUIRED:{group}"
            )

        group_mass = _group_totals(normalized, group)
        if max(group_mass.values()) <= _EPS:
            retention_by_group[group] = 1.0
            continue

        try:
            retention = starter_retention_probability(
                artifact,
                position_group=group,
                quarter=state["quarter"],
                clock_seconds_remaining=state["clock_seconds_remaining"],
                score_margin=state["score_margin"],
            )
        except CFBParticipationModelError as exc:
            raise CFBPropStateAllocatorError(
                f"CFB_PROP_STATE_POSITION_MODEL_REQUIRED:{group}:{exc}"
            ) from exc
        if not 0.0 <= retention <= 1.0:
            raise CFBPropStateAllocatorError(
                f"CFB_PROP_STATE_RETENTION_INVALID:{group}"
            )
        retention_by_group[group] = float(retention)

        for metric in _METRICS:
            starter_indices = [
                index for index in indices if normalized[index]["starter"]
            ]
            backup_indices = [
                index for index in indices if not normalized[index]["starter"]
            ]
            starter_mass = float(
                sum(normalized[index][metric] for index in starter_indices)
            )
            vacated = starter_mass * (1.0 - retention)
            if vacated <= _EPS:
                continue

            backup_weight = float(
                sum(normalized[index][metric] for index in backup_indices)
            )
            if backup_weight <= _EPS:
                raise CFBPropStateAllocatorError(
                    f"CFB_PROP_STATE_BACKUP_SHARE_REQUIRED:{group}:{metric}"
                )

            for index in starter_indices:
                adjusted[index][metric] = (
                    normalized[index][metric] * retention
                )
            for index in backup_indices:
                weight = normalized[index][metric] / backup_weight
                adjusted[index][metric] = normalized[index][metric] + vacated * weight

        before = _group_totals(normalized, group)
        after = _group_totals(adjusted, group)
        for metric in _METRICS:
            if abs(before[metric] - after[metric]) > 1e-10:
                raise CFBPropStateAllocatorError(
                    f"CFB_PROP_STATE_MASS_NOT_CONSERVED:{group}:{metric}"
                )

    source_manifest = [
        {
            "player_id": row["player_id"],
            "position_group": row["position_group"],
            "starter": row["starter"],
            "source_sha256": row["source_sha256"],
        }
        for row in normalized
    ]
    result = {
        "schema_version": SCHEMA_VERSION,
        "sport": "CFB",
        "model_role": "GAME_STATE_PLAYER_OPPORTUNITY_ALLOCATOR_CANDIDATE",
        "participation_artifact_sha256": artifact["artifact_sha256"],
        "participation_training_source_manifest_sha256": artifact[
            "training_source_manifest_sha256"
        ],
        "player_source_manifest_sha256": _canonical_sha256(source_manifest),
        "state": state,
        "starter_retention_probability_by_position": retention_by_group,
        "players": [
            {
                "player_id": row["player_id"],
                "position_group": row["position_group"],
                "starter": row["starter"],
                "rush_share": float(row["rush_share"]),
                "target_share": float(row["target_share"]),
                "red_zone_share": float(row["red_zone_share"]),
            }
            for row in adjusted
        ],
        "validation_status": "UNVALIDATED_CANDIDATE",
        "market_inputs_consumed": False,
        "promotion_authority": False,
        "activation_authority": False,
        "official_authority": False,
        "requires_forward_validation": True,
    }
    result["allocator_sha256"] = _canonical_sha256(result)
    return result


__all__ = [
    "CFBPropStateAllocatorError",
    "SCHEMA_VERSION",
    "allocate_cfb_player_opportunity",
]
