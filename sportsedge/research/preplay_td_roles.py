"""Research Engine B challenger: role weights from preplay field position.

Uses existing Engine A paths and Engine B attribution/reconciliation contracts.
Different target and rush shares avoid assigning every TD to one blended role.
No production class, frozen model bytes, or registry entry is modified.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Mapping
from types import MappingProxyType

from sportsedge.core.simulate.drive_play import FootballPlayPath
from sportsedge.core.simulate.usage import (
    AttributedFootballPath, AttributedPlay, EngineBUsageAllocator,
    _is_offensive_touchdown,
)


@dataclass(frozen=True)
class ZoneRole:
    inside5_rush: float
    inside20_rush: float
    inside10_target: float
    inside20_target: float

    def __post_init__(self):
        for value in vars(self).values():
            if isinstance(value, bool) or not isfinite(value) or not 0 <= value <= 1:
                raise ValueError("ZONE_ROLE_SHARE_INVALID")


def stabilized_role_shares(counts: Mapping[str, int], prior: Mapping[str, float],
                           *, prior_strength: float) -> dict[str, float]:
    """Dirichlet posterior shares for one team's one opportunity category.

    Inputs must contain all eligible players, including players with zero events.
    Missing observations are not zeros; callers must reject missing source data.
    Prior strength is an explicit research policy input, never fitted here.
    """
    if not counts or set(counts) != set(prior):
        raise ValueError("ROLE_ROSTER_MISMATCH")
    if any(not key for key in counts):
        raise ValueError("ROLE_PLAYER_ID_REQUIRED")
    if any(type(v) is not int or v < 0 for v in counts.values()):
        raise ValueError("ROLE_COUNTS_INVALID")
    if (isinstance(prior_strength, bool) or not isfinite(prior_strength)
            or prior_strength <= 0):
        raise ValueError("ROLE_PRIOR_STRENGTH_INVALID")
    if any(isinstance(v, bool) or not isfinite(v) or not 0 <= v <= 1 for v in prior.values()):
        raise ValueError("ROLE_PRIOR_INVALID")
    if abs(sum(prior.values()) - 1) > 1e-9:
        raise ValueError("ROLE_PRIOR_MASS_INVALID")
    total = sum(counts.values()) + prior_strength
    return {key: (counts[key] + prior_strength * prior[key]) / total for key in counts}


class PreplayRoleAllocator(EngineBUsageAllocator):
    """Opt-in research allocation with the parent's seeded RNG and shared paths.

    Supplied shares are already stabilized across the roster. They replace,
    rather than multiply, open-field shares in the applicable zone. They are
    subsequently conditioned on the parent's simulated active/route candidate
    set. Passing TDs remain passer stats, never personal TD scorer events.
    """
    version = "preplay_zone_usage_research_v1"

    def __init__(self, home_usage, away_usage, *, roles: Mapping[str, ZoneRole], seed: int):
        super().__init__(home_usage, away_usage, seed=seed)
        players = [p for u in (home_usage, away_usage) for p in u.players]
        if len({p.player_id for p in players}) != len(players):
            raise ValueError("CROSS_TEAM_PLAYER_ID_COLLISION")
        if set(roles) != {p.player_id for p in players}:
            raise ValueError("COMPLETE_ZONE_ROLE_ROSTER_REQUIRED")
        for p in players:
            role = roles[p.player_id]
            if not isinstance(role, ZoneRole):
                raise TypeError("ZONE_ROLE_REQUIRED")
            if p.rush_share == 0 and (role.inside5_rush or role.inside20_rush):
                raise ValueError("ZONE_RUSHER_MUST_HAVE_BASE_ROLE")
            if p.target_share == 0 and (role.inside10_target or role.inside20_target):
                raise ValueError("ZONE_TARGET_MUST_HAVE_BASE_ROLE")
        self.roles = MappingProxyType(dict(roles))
        self._yardline = None

    def _weighted_pick(self, players, *, weight_name, red_zone):
        if self._yardline is None:
            raise ValueError("PREPLAY_POSITION_REQUIRED")
        if weight_name == "rush_share":
            field = "inside5_rush" if self._yardline <= 5 else "inside20_rush"
        elif weight_name == "target_share":
            field = "inside10_target" if self._yardline <= 10 else "inside20_target"
        else:
            raise ValueError("UNSUPPORTED_ZONE_ROLE")
        weights = [getattr(self.roles[p.player_id], field) if self._yardline <= 20
                   else getattr(p, weight_name) for p in players]
        total = sum(weights)
        if total <= 0:
            raise ValueError("ZONE_ROLE_CANDIDATE_MASS_ZERO")
        return players[int(self.rng.choice(len(players), p=[w / total for w in weights]))]

    def attribute(self, path: FootballPlayPath) -> AttributedFootballPath:
        if not isinstance(path, FootballPlayPath):
            raise TypeError("FOOTBALL_PLAY_PATH_REQUIRED")
        if path.home_team != self.home_usage.team or path.away_team != self.away_usage.team:
            raise ValueError("USAGE_PATH_TEAM_MISMATCH")
        self._assert_resolved(self.home_usage)
        self._assert_resolved(self.away_usage)

        attributed: list[AttributedPlay] = []
        for play in path.plays:
            usage = self.home_usage if play.possession == path.home_team else self.away_usage
            active, fallback = self._active_set(usage)
            active_ids = {player.player_id for player in active}
            play_type = play.play_type.upper()
            passer_id: str | None = None
            target_id: str | None = None
            receiver_id: str | None = None
            rusher_id: str | None = None
            touchdown_scorer_id: str | None = None
            self._yardline = play.yardline_100
            red_zone = play.yardline_100 <= 20

            if play_type == "PASS":
                passer_id = usage.quarterback_id
                target, target_fallback = self._target(usage, active, red_zone=red_zone)
                fallback = fallback or target_fallback
                target_id = target.player_id
                active_ids.add(target_id)
                if play.pass_complete:
                    receiver_id = target_id
                    if _is_offensive_touchdown(play):
                        touchdown_scorer_id = target_id
            elif play_type == "RUSH":
                rusher, rush_fallback = self._rusher(usage, active, red_zone=red_zone)
                fallback = fallback or rush_fallback
                rusher_id = rusher.player_id
                active_ids.add(rusher_id)
                if _is_offensive_touchdown(play):
                    touchdown_scorer_id = rusher_id

            attributed.append(
                AttributedPlay(
                    base_play=play,
                    active_player_ids=tuple(sorted(active_ids)),
                    passer_id=passer_id,
                    target_id=target_id,
                    receiver_id=receiver_id,
                    rusher_id=rusher_id,
                    touchdown_scorer_id=touchdown_scorer_id,
                    allocation_fallback=fallback,
                )
            )

        result = AttributedFootballPath(
            base_path=path,
            home_usage=self.home_usage,
            away_usage=self.away_usage,
            plays=tuple(attributed),
        )
        result.assert_reconciliation()
        return result


def summarize_offensive_touchdowns(paths, *, player_ids):
    """Marginals and an all-selected-score joint event from the SAME samples.

    Offensive regulation scope only. This is not book-complete ATTD: return,
    defensive and overtime scoring require the complete-scorer integration.
    """
    from sportsedge.core.simulate.player_markets import derive_player_stat_market

    materialized = list(paths)
    players = tuple(player_ids)
    if not players or len(set(players)) != len(players):
        raise ValueError("UNIQUE_SELECTED_PLAYERS_REQUIRED")
    if not materialized:
        raise ValueError("PATHS_REQUIRED")
    identities = [(p.base_path.game_id, p.base_path.simulation_id) for p in materialized]
    if len(set(identities)) != len(identities):
        raise ValueError("DUPLICATE_SIMULATION_ID")
    marginals = {}
    for player in players:
        # Existing readout verifies game/player/team identity and participation.
        marginals[player] = {
            str(n) + '+': derive_player_stat_market(materialized, player_id=player,
                stat='touchdowns', line=n-.5)['over'] for n in (1, 2, 3)
        }
    for path in materialized:
        path.assert_reconciliation()
    counts = [p.player_stats() for p in materialized]
    joint = sum(all(row[player]['touchdowns'] >= 1 for player in players)
                for row in counts) / len(counts)
    return {'scope': 'OFFENSIVE_REGULATION_ONLY', 'probabilities': marginals,
            'all_selected_score_probability': joint, 'simulations': len(counts),
            'status': 'RESEARCH_UNVALIDATED', 'official_eligible': False, 'stake': 0.0}
