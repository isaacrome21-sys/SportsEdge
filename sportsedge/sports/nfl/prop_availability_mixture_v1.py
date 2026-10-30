"""Experimental active/inactive availability mixture for NFL prop research.

This is a separate, market-blind challenger. It does not replace the existing
role simulator, reprice frozen boards, or grant Model_P / PLAY authority.

``stabilize_role`` returns role means already multiplied by the pregame
availability probability. The incumbent simulates those attenuated means on
*every* path. A binary game-level availability state instead gives the player
their conditional role on active paths and zero usage on inactive paths.
Both constructions have the same expectation but different tails.

The assumption that ``availability_probability`` means all-or-nothing game
participation must be checked on historical, point-in-time role evidence before
this research variant can be considered for promotion.
"""
from __future__ import annotations

from hashlib import sha256
from math import isfinite
import random
from typing import Any, Mapping

from .prop_role_challenger import (
    PropChallengerError,
    PropSimulation,
    RoleProjection,
    simulate_player_props,
)


MODEL_ID = "NFL_ROLE_PROP_AVAILABILITY_MIXTURE_CHALLENGER_V1"
STATUS = "RESEARCH_ONLY_NO_MODEL_P"


def simulate_availability_mixture(
    *,
    role: RoleProjection,
    efficiency: Mapping[str, Any],
    paths: int = 50_000,
    seed: int = 1,
    shared_pace_sigma: float = 0.12,
) -> PropSimulation:
    """Sample one availability state per game-path across all prop families.

    The received role contains *unconditional* means from ``stabilize_role``;
    divide only when availability is strictly positive. Invalid or inconsistent
    inputs fail closed, and the existing simulator validates all efficiency
    inputs and simulation settings.
    """
    if not isinstance(role, RoleProjection):
        raise PropChallengerError("ROLE_PROJECTION_REQUIRED")
    q = float(role.availability_probability)
    if not isfinite(q) or not 0.0 <= q <= 1.0:
        raise PropChallengerError("BAD_AVAILABILITY_PROBABILITY")
    means = (role.pass_attempt_mean, role.rush_attempt_mean, role.target_mean)
    if any(not isfinite(v) or v < 0.0 for v in means):
        raise PropChallengerError("BAD_UNCONDITIONAL_ROLE_MEAN")
    if q == 0.0 and any(v != 0.0 for v in means):
        raise PropChallengerError("ZERO_AVAILABILITY_WITH_NONZERO_ROLE")

    conditional = RoleProjection(
        entity_id=role.entity_id,
        pass_attempt_mean=role.pass_attempt_mean / q if q else 0.0,
        rush_attempt_mean=role.rush_attempt_mean / q if q else 0.0,
        target_mean=role.target_mean / q if q else 0.0,
        availability_probability=1.0,
        history_games=role.history_games,
        source=role.source,
    )
    active = simulate_player_props(
        role=conditional,
        efficiency=efficiency,
        paths=paths,
        seed=seed,
        shared_pace_sigma=shared_pace_sigma,
    )

    # Independent, domain-separated RNG leaves the active player distribution
    # unchanged and makes the q=1 paths byte-equal to the incumbent baseline.
    mask_seed = int.from_bytes(
        sha256(f"availability-mixture-v1:{int(seed)}".encode()).digest()[:8],
        "big",
    )
    mask_rng = random.Random(mask_seed)
    zero = {key: 0 for key in active.paths[0]}
    mixed = tuple(
        outcome if mask_rng.random() < q else zero.copy()
        for outcome in active.paths
    )
    return PropSimulation(
        entity_id=role.entity_id,
        paths=mixed,
        seed=int(seed),
        model_id=MODEL_ID,
        status=STATUS,
    )


__all__ = ["MODEL_ID", "STATUS", "simulate_availability_mixture"]
