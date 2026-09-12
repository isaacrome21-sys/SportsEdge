"""Research-only NFL M2 V2F PIT state blend.

V2F tests the preregistered early-season feature-state hypothesis without
changing production M2, the market binding, or any frozen promotion gate.
Production history rows are built first through the exact production policy.
This module then replaces only the market-blind season-to-date efficiency state
with a convex blend of strictly previous-season completed state and strictly
current-season completed-before-kick state, using the already-fitted weekly
prior weight carried by the production row.

The downstream probability engine remains V2D structured mean + observed
integer score support. Sportsbook fields are never used to construct features.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .m2_history_features import _Stats, _aggregate_games, _game_sort_key
from .m2_history_policy import build_nfl_m2_history_rows

NFL_M2_V2F_PIT_STATE_CONTRACT = "NFL_M2_V2F_PIT_PRIOR_CURRENT_STATE_BLEND_V1"


@dataclass(frozen=True)
class V2FStateView:
    off_epa: float
    def_epa: float
    pass_epa: float
    rush_epa: float
    pressure_for: float
    pressure_allowed: float
    success_rate: float
    explosive_rate: float
    prior_available: bool
    prior_weight_applied: float


def _blend(current: float, prior: float, weight: float, *, prior_available: bool) -> float:
    """Blend prior/current only when a real completed prior-season state exists."""
    w = float(weight)
    if not 0.0 <= w <= 1.0:
        raise ValueError("NFL_M2_V2F_PRIOR_WEIGHT_INVALID")
    if not prior_available:
        return float(current)
    return (1.0 - w) * float(current) + w * float(prior)


def blended_state_view(
    current: _Stats,
    prior: _Stats | None,
    *,
    prior_weight: float,
) -> V2FStateView:
    """Return the frozen-weight, market-blind state used by V2F.

    Missing prior-season state never means a synthetic zero prior. In that case
    the current PIT state is retained unchanged.
    """
    available = prior is not None
    p = prior if prior is not None else _Stats()
    w = float(prior_weight)
    applied = w if available else 0.0
    return V2FStateView(
        off_epa=_blend(current.off_epa(), p.off_epa(), w, prior_available=available),
        def_epa=_blend(current.def_epa(), p.def_epa(), w, prior_available=available),
        pass_epa=_blend(current.pass_epa(), p.pass_epa(), w, prior_available=available),
        rush_epa=_blend(current.rush_epa(), p.rush_epa(), w, prior_available=available),
        pressure_for=_blend(current.pressure_for_rate(), p.pressure_for_rate(), w, prior_available=available),
        pressure_allowed=_blend(current.pressure_allowed_rate(), p.pressure_allowed_rate(), w, prior_available=available),
        success_rate=_blend(current.success_rate(), p.success_rate(), w, prior_available=available),
        explosive_rate=_blend(current.explosive_rate(), p.explosive_rate(), w, prior_available=available),
        prior_available=available,
        prior_weight_applied=applied,
    )


def _replace_state_features(
    features: Mapping[str, Any],
    *,
    own: V2FStateView,
    opponent: V2FStateView,
) -> dict[str, Any]:
    """Replace only fields derived from the team/opponent efficiency state."""
    out = dict(features)
    out["adj_off_epa"] = own.off_epa - opponent.def_epa
    out["adj_def_epa"] = own.def_epa - opponent.off_epa
    out["pass_epa"] = own.pass_epa
    out["rush_epa"] = own.rush_epa
    out["pressure_for"] = own.pressure_for
    out["pressure_allowed"] = own.pressure_allowed
    out["success_rate"] = own.success_rate
    out["explosive_rate"] = own.explosive_rate
    return out


def build_nfl_m2_v2f_pit_state_rows(
    schedule_rows: Iterable[Mapping[str, Any]],
    pbp_rows: Iterable[Mapping[str, Any]],
    participation_rows: Iterable[Mapping[str, Any]],
    depth_rows: Iterable[Mapping[str, Any]],
    stadium_rows: Iterable[Mapping[str, Any]],
    *,
    prior_decay_curves: Mapping[int, Mapping[int, float]],
    neutral_site_policy: str = "exclude_from_evaluation",
) -> list[dict[str, Any]]:
    """Build diagnostic rows with the preregistered PIT state blend.

    The production-policy builder remains the authority for row eligibility,
    timestamps, QB identity, environment, geography, and source semantics.
    V2F changes only the eight market-blind team-state features listed above.
    """
    schedule = [dict(row) for row in schedule_rows]
    pbp = [dict(row) for row in pbp_rows]
    participation = [dict(row) for row in participation_rows]
    depth = [dict(row) for row in depth_rows]
    stadiums = [dict(row) for row in stadium_rows]

    production_rows = build_nfl_m2_history_rows(
        schedule,
        pbp,
        participation,
        depth,
        stadiums,
        prior_decay_curves=prior_decay_curves,
        neutral_site_policy=neutral_site_policy,
    )
    by_game = {str(row["game_id"]): dict(row) for row in production_rows}
    if len(by_game) != len(production_rows):
        raise ValueError("NFL_M2_V2F_DUPLICATE_PRODUCTION_GAME_ID")

    game_stats, _ = _aggregate_games(pbp, participation)
    regular = [dict(row) for row in schedule if str(row.get("game_type") or "REG").upper() == "REG"]
    regular.sort(key=_game_sort_key)

    current_state: dict[tuple[int, str], _Stats] = {}
    completed_state: dict[tuple[int, str], _Stats] = {}
    active_season: int | None = None
    output: list[dict[str, Any]] = []

    for game in regular:
        season = int(game["season"])
        gid = str(game.get("game_id") or "").strip()
        home = str(game.get("home_team") or "").strip()
        away = str(game.get("away_team") or "").strip()
        if not gid or not home or not away:
            raise ValueError("NFL_M2_V2F_GAME_IDENTITY_MISSING")

        if active_season is None:
            active_season = season
        elif season != active_season:
            for (state_season, team), stats in current_state.items():
                if state_season == active_season:
                    completed_state[(state_season, team)] = stats
            active_season = season

        base = by_game.get(gid)
        if base is not None:
            home_features = dict(base.get("home_features") or {})
            away_features = dict(base.get("away_features") or {})
            if not home_features or not away_features:
                raise ValueError("NFL_M2_V2F_PRODUCTION_FEATURES_MISSING")
            home_weight = float(home_features["prior_weight"])
            away_weight = float(away_features["prior_weight"])
            if abs(home_weight - away_weight) > 1e-12:
                raise ValueError("NFL_M2_V2F_ASYMMETRIC_PRIOR_WEIGHT")

            home_current = current_state.get((season, home), _Stats())
            away_current = current_state.get((season, away), _Stats())
            home_prior = completed_state.get((season - 1, home))
            away_prior = completed_state.get((season - 1, away))
            home_view = blended_state_view(home_current, home_prior, prior_weight=home_weight)
            away_view = blended_state_view(away_current, away_prior, prior_weight=away_weight)

            row = dict(base)
            row["home_features"] = _replace_state_features(home_features, own=home_view, opponent=away_view)
            row["away_features"] = _replace_state_features(away_features, own=away_view, opponent=home_view)
            provenance = dict(row.get("feature_provenance") or {})
            provenance["v2f_pit_state_contract"] = NFL_M2_V2F_PIT_STATE_CONTRACT
            provenance["v2f_prior_weight_source"] = "PRODUCTION_EARLIER_SEASONS_ONLY_WEEKLY_DECAY"
            provenance["v2f_market_inputs_used"] = False
            row["feature_provenance"] = provenance
            row["v2f_state_audit"] = {
                "home_prior_available": home_view.prior_available,
                "away_prior_available": away_view.prior_available,
                "home_prior_weight_applied": home_view.prior_weight_applied,
                "away_prior_weight_applied": away_view.prior_weight_applied,
            }
            output.append(row)

        # Current game enters state only after its feature row has been emitted.
        for team in (home, away):
            stats = game_stats.get((gid, team))
            if stats is not None:
                current_state.setdefault((season, team), _Stats()).add(stats)

    if len(output) != len(production_rows):
        raise ValueError("NFL_M2_V2F_HISTORY_ROW_COUNT_MISMATCH")
    return output
