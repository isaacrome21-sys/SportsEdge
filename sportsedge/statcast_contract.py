"""Fail-closed Statcast feature contract for SportsEdge MLB production models.

This module does not infer missing values and does not permit legacy artifacts to
masquerade as Statcast-aware. A production artifact must explicitly declare the
contract version and the exact Statcast-derived feature names it consumes.
"""
from __future__ import annotations

from typing import Any, Mapping

STATCAST_CONTRACT_VERSION = "SPORTSEDGE_STATCAST_V1"

GAME_STATCAST_FEATURES = (
    "off_xwoba",
    "off_xslg",
    "off_barrel_rate",
    "off_hard_hit_rate",
    "off_avg_exit_velocity",
    "opp_sp_xwoba_allowed",
    "opp_sp_barrel_rate_allowed",
    "opp_sp_hard_hit_rate_allowed",
    "opp_sp_avg_exit_velocity_allowed",
)

NRFI_STATCAST_FEATURES = (
    "away_top_order_xwoba",
    "home_top_order_xwoba",
    "away_top_order_barrel_rate",
    "home_top_order_barrel_rate",
    "away_sp_xwoba_allowed",
    "home_sp_xwoba_allowed",
    "away_sp_hard_hit_rate_allowed",
    "home_sp_hard_hit_rate_allowed",
)

HITTER_STATCAST_FEATURES = (
    "batter_xwoba",
    "batter_xslg",
    "batter_barrel_rate",
    "batter_hard_hit_rate",
    "batter_avg_exit_velocity",
    "opp_sp_xwoba_allowed",
    "opp_sp_hard_hit_rate_allowed",
)

class StatcastContractError(ValueError):
    pass


def require_statcast_artifact(artifact: Mapping[str, Any], *, kind: str) -> None:
    if not isinstance(artifact, Mapping):
        raise StatcastContractError("STATCAST_ARTIFACT_NOT_MAPPING")
    if artifact.get("statcast_contract_version") != STATCAST_CONTRACT_VERSION:
        raise StatcastContractError("STATCAST_CONTRACT_MISSING_OR_WRONG_VERSION")
    if artifact.get("statcast_consumed_by_model") is not True:
        raise StatcastContractError("STATCAST_NOT_CONSUMED_BY_MODEL")
    expected = GAME_STATCAST_FEATURES if kind == "game" else NRFI_STATCAST_FEATURES if kind == "nrfi" else HITTER_STATCAST_FEATURES if kind == "hitter" else None
    if expected is None:
        raise StatcastContractError(f"STATCAST_KIND_UNSUPPORTED:{kind}")
    declared = tuple(artifact.get("statcast_features") or ())
    missing = tuple(x for x in expected if x not in declared)
    if missing:
        raise StatcastContractError(f"STATCAST_FEATURES_MISSING:{','.join(missing)}")


def require_statcast_row(row: Mapping[str, Any], *, kind: str) -> None:
    if not isinstance(row, Mapping):
        raise StatcastContractError("STATCAST_ROW_NOT_MAPPING")
    expected = GAME_STATCAST_FEATURES if kind == "game" else NRFI_STATCAST_FEATURES if kind == "nrfi" else HITTER_STATCAST_FEATURES if kind == "hitter" else None
    if expected is None:
        raise StatcastContractError(f"STATCAST_KIND_UNSUPPORTED:{kind}")
    for name in expected:
        value = row.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise StatcastContractError(f"STATCAST_VALUE_MISSING_OR_INVALID:{name}")
