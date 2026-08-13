"""Live feature assembly for SportsEdge Statcast V5.

This module intentionally contains no sportsbook inputs.  It consumes a rolling
prior-only Statcast state, exact probable-starter identities, and a resolved
projected/confirmed batting order.  Missing evidence blocks scoring.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence

from .statcast_contract import GAME_STATCAST_FEATURES, NRFI_STATCAST_FEATURES
from .statcast_v5_data import PlateAppearance, StatcastDataError, V5State, update_state

MIN_TEAM_BBE = 75
MIN_PITCHER_BBE = 30
MIN_BATTER_BBE = 20

class StatcastV5LiveError(ValueError):
    pass


def build_prior_state(rows: Sequence[PlateAppearance], transformer: Any, *, initial_state: V5State | None = None) -> V5State:
    """Apply only rows already proven to predate the live target cutoff."""
    state = initial_state if initial_state is not None else V5State()
    by_game: dict[tuple[str, int], list[PlateAppearance]] = defaultdict(list)
    for row in rows:
        by_game[(row.game_date, int(row.game_pk))].append(row)
    for key in sorted(by_game):
        update_state(state, by_game[key], transformer)
    return state


def resolved_top3(lineup_rows: Iterable[Mapping[str, Any]]) -> tuple[int, int, int]:
    """Resolve slots 1-3 from a projected/confirmed primary order, fail closed."""
    primary: dict[int, int] = {}
    for raw in lineup_rows:
        try:
            slot = int(raw.get("slot")); player = int(raw.get("player_id")); sequence = int(raw.get("sequence", 0))
        except Exception as exc:
            raise StatcastV5LiveError("STATCAST_LINEUP_ROW_INVALID") from exc
        if sequence != 0 or slot not in (1, 2, 3):
            continue
        if slot in primary and primary[slot] != player:
            raise StatcastV5LiveError(f"STATCAST_LINEUP_SLOT_AMBIGUOUS:{slot}")
        primary[slot] = player
    if set(primary) != {1, 2, 3} or len(set(primary.values())) != 3:
        raise StatcastV5LiveError("STATCAST_TOP3_LINEUP_UNRESOLVED")
    return primary[1], primary[2], primary[3]


def _values(state, key, *, min_bbe: int, label: str) -> dict[str, float]:
    try:
        return state[key].values(min_bbe=min_bbe)
    except StatcastDataError as exc:
        raise StatcastV5LiveError(f"{label}_PRIOR_EVIDENCE_INSUFFICIENT:{key}:{exc}") from exc


def _top_metric(state: V5State, players: Sequence[int], metric: str) -> float:
    values=[]
    for pid in players:
        b=_values(state.batter,int(pid),min_bbe=MIN_BATTER_BBE,label="BATTER")
        values.append(float(b[metric]))
    return sum(values)/len(values)


def assemble_live_statcast_features(
    state: V5State,
    *,
    away_team: str,
    home_team: str,
    away_starter_id: int,
    home_starter_id: int,
    away_top3: Sequence[int],
    home_top3: Sequence[int],
) -> dict[str, Any]:
    """Return V5 game and first-inning columns in the frozen contract order."""
    if not away_team or not home_team or away_team == home_team:
        raise StatcastV5LiveError("STATCAST_TEAM_IDENTITY_INVALID")
    if int(away_starter_id) <= 0 or int(home_starter_id) <= 0:
        raise StatcastV5LiveError("STATCAST_STARTER_IDENTITY_INVALID")
    if len(tuple(away_top3)) != 3 or len(tuple(home_top3)) != 3:
        raise StatcastV5LiveError("STATCAST_TOP3_LINEUP_UNRESOLVED")

    away_off=_values(state.team,away_team,min_bbe=MIN_TEAM_BBE,label="TEAM")
    home_off=_values(state.team,home_team,min_bbe=MIN_TEAM_BBE,label="TEAM")
    away_sp=_values(state.pitcher,int(away_starter_id),min_bbe=MIN_PITCHER_BBE,label="PITCHER")
    home_sp=_values(state.pitcher,int(home_starter_id),min_bbe=MIN_PITCHER_BBE,label="PITCHER")

    def game_side(off: Mapping[str,float], opp: Mapping[str,float]) -> dict[str,float]:
        return {
            "off_xwoba":float(off["xcontact_woba"]),
            "off_xba":float(off["xhit"]),
            "off_barrel_rate":float(off["barrel_rate"]),
            "off_hard_hit_rate":float(off["hard_hit_rate"]),
            "off_avg_exit_velocity":float(off["avg_exit_velocity"]),
            "opp_sp_xwoba_allowed":float(opp["xcontact_woba"]),
            "opp_sp_xba_allowed":float(opp["xhit"]),
            "opp_sp_barrel_rate_allowed":float(opp["barrel_rate"]),
            "opp_sp_hard_hit_rate_allowed":float(opp["hard_hit_rate"]),
            "opp_sp_avg_exit_velocity_allowed":float(opp["avg_exit_velocity"]),
        }

    first={
        "away_top_order_xwoba":_top_metric(state,away_top3,"xcontact_woba"),
        "home_top_order_xwoba":_top_metric(state,home_top3,"xcontact_woba"),
        "away_top_order_barrel_rate":_top_metric(state,away_top3,"barrel_rate"),
        "home_top_order_barrel_rate":_top_metric(state,home_top3,"barrel_rate"),
        "away_sp_xwoba_allowed":float(away_sp["xcontact_woba"]),
        "home_sp_xwoba_allowed":float(home_sp["xcontact_woba"]),
        "away_sp_hard_hit_rate_allowed":float(away_sp["hard_hit_rate"]),
        "home_sp_hard_hit_rate_allowed":float(home_sp["hard_hit_rate"]),
    }
    away=game_side(away_off,home_sp); home=game_side(home_off,away_sp)
    if tuple(away) != tuple(GAME_STATCAST_FEATURES) or tuple(home) != tuple(GAME_STATCAST_FEATURES):
        raise StatcastV5LiveError("GAME_STATCAST_FEATURE_ORDER_MISMATCH")
    if tuple(first) != tuple(NRFI_STATCAST_FEATURES):
        raise StatcastV5LiveError("NRFI_STATCAST_FEATURE_ORDER_MISMATCH")
    return {
        "away":away,
        "home":home,
        "first_inning":first,
        "game_feature_order":tuple(GAME_STATCAST_FEATURES),
        "first_inning_feature_order":tuple(NRFI_STATCAST_FEATURES),
    }
