"""Canonical-path NFL joint score distribution (RESEARCH ONLY, default OFF).

The canonical game engine (artifacts/free_models.py, Lane A) is analytic and
emits only team score means; the wired team-total/period/alternate derivative
pricers need joint score paths and therefore return NO_ENGINE. This module
builds those paths from the Lane A (market-blind) means pushed through the
FROZEN discrete_v2 score shape (config/nfl_discrete_v2_freeze.json:
negative-binomial marginals + key-number margin lifts), sampled with a seed
derived from the fixture identity.

Honesty constraints:
* Lane A only. Lane B (market-anchored) means are refused so an anchored
  source cannot launder itself into an "independent" derivative.
* No market input, no tuning; the shape artifact is used as frozen.
* Not validated. N3 (research/mlb-market-legs-20261014, REPORT_STAGE2 s5)
  found the NFL totals level DOES_NOT_BEAT_BASELINE (priors only), so these
  paths inherit an unvalidated level. Output is research-only.
"""
from __future__ import annotations

import hashlib
from math import isfinite
from typing import Any, Mapping

from sportsedge.sports.nfl.discrete_v2 import (
    load_freeze, means_from_attempt9, score_grid)
from sportsedge.sports.nfl.unified_market_engine import sample_score_paths

ENABLED_BY_DEFAULT = False
SOURCE = "LANE_A_MEANS_X_DISCRETE_V2_FROZEN_SHAPE"
DEFAULT_N_SIMS = 20000
_EXISTING_KEYS = ("simulation_rows", "score_paths", "joint_score_distribution")


class CanonicalJointDistributionError(ValueError):
    pass


def _lane_a_means(game_result: Mapping[str, Any]) -> tuple[float, float]:
    if str(game_result.get("sport") or "").upper() != "NFL":
        raise CanonicalJointDistributionError("NFL_CANONICAL_DIST_SPORT_NOT_NFL")
    lane = (game_result.get("pricing_lanes") or {}).get("lane_a_independent")
    if not isinstance(lane, Mapping):
        raise CanonicalJointDistributionError("NFL_CANONICAL_DIST_LANE_A_MISSING")
    out = []
    for key in ("home_mean", "away_mean"):
        v = lane.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not isfinite(v) or v <= 0:
            raise CanonicalJointDistributionError(f"NFL_CANONICAL_DIST_{key.upper()}_INVALID")
        out.append(float(v))
    return out[0], out[1]


def _seed(game_result: Mapping[str, Any], home: float, away: float) -> int:
    ident = "|".join([str(game_result.get("away") or ""), str(game_result.get("home") or ""),
                      repr(round(home, 6)), repr(round(away, 6))])
    return int(hashlib.sha256(ident.encode()).hexdigest()[:12], 16)


def canonical_joint_score_distribution(game_result: Mapping[str, Any], *,
                                       n_sims: int = DEFAULT_N_SIMS) -> dict[str, Any]:
    home, away = _lane_a_means(game_result)
    freeze = load_freeze()
    means = means_from_attempt9(home - away, home + away)
    grid = score_grid(means["mean_home"], means["mean_away"], freeze)
    seed = _seed(game_result, home, away)
    rows = sample_score_paths(grid, n_sims=n_sims, seed=seed)
    for r in rows:
        r["home_score"], r["away_score"] = int(r["home_score"]), int(r["away_score"])
    return {"rows": rows, "meta": {
        "source": SOURCE, "lane": "LANE_A_INDEPENDENT",
        "lane_a_home_mean": home, "lane_a_away_mean": away,
        "shape_freeze_sha256": str(freeze.get("artifact_sha256")),
        "n_sims": n_sims, "seed": seed,
        "market_inputs": False, "validated": False, "research_only": True,
    }}


def attach_canonical_distribution(game_result: Mapping[str, Any], *,
                                  n_sims: int = DEFAULT_N_SIMS) -> Mapping[str, Any]:
    """Return a copy carrying joint_score_distribution; existing paths win."""
    if any(isinstance(game_result.get(k), list) and game_result.get(k) for k in _EXISTING_KEYS):
        return game_result
    built = canonical_joint_score_distribution(game_result, n_sims=n_sims)
    out = dict(game_result)
    out["joint_score_distribution"] = built["rows"]
    out["joint_score_distribution_meta"] = built["meta"]
    return out
