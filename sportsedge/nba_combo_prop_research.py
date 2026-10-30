"""NBA combo props P+R, P+A, R+A — unregistered research module.

Derived from the frozen V1 construction (sportsedge.nba_prop_empirical,
NBA_PROP_EMPIRICAL_V1) WITHOUT modifying it: same store, same
n/(n+5) player-vs-position-pool mixture, same >=10 same-season prior
gate, same strict point-in-time date rule, same B1->B2 pool fallback.
Like V1's PRA, each combo is the same game's own sum (never an
independence assumption across stats).

V1 is frozen (prereg #2424); this module imports it read-only and adds
no stat to V1.STATS.  Governance: RESEARCH_UNSCREENED (until a screen
is filed) / SCREEN, NOT_VALIDATED, unregistered, eligible=false,
play_allowed=false.  No quotes, no EV.
"""
from __future__ import annotations

import math

import numpy as np

from sportsedge import nba_prop_empirical as v1

ENGINE_ID = "NBA_COMBO_PROP_RESEARCH_V1"
COMBOS = {"pr": ("points", "rebounds"), "pa": ("points", "assists"),
          "ra": ("rebounds", "assists")}
GOVERNANCE = {"state": "SCREEN", "registration": "UNREGISTERED",
              "validation_status": "NOT_VALIDATED", "eligible": False,
              "play_allowed": False}


def combo_value(game, combo: str) -> float:
    a, b = COMBOS[combo]
    return float(game[a]) + float(game[b])


def _prior(store, pid, combo, target):
    p = store._players.get(str(pid))
    return [] if p is None else [combo_value(g, combo) for g in p["games"]
                                 if g["game_date"] < target]


def _pool(store, group, combo, target):
    return [combo_value(g, combo) for g in store._league
            if g["game_date"] < target
            and (group is None or store._players[g["player_id"]]["group"] == group)]


def price_combo(store, player_id, combo: str, line, target_date) -> dict:
    base = {"engine_id": ENGINE_ID, "derived_from": v1.ENGINE_ID,
            "combo": combo, **GOVERNANCE,
            "participation_feed": "NOT_WIRED"}
    if not isinstance(combo, str) or combo not in COMBOS:  # t235: never a TypeError
        return {**base, "status": "REFUSED", "reason": "NBA_COMBO_UNSUPPORTED"}
    bad = lambda det: {**base, "status": "REFUSED",
                       "reason": v1.REFUSAL_LINE_INVALID, "detail": det}
    if isinstance(line, (bool, np.bool_)):
        return bad("LINE_BOOL")
    if not isinstance(line, (int, float, str)):
        return bad("LINE_TYPE")
    if isinstance(line, str) and (not line.strip() or line != line.strip()):
        return bad("LINE_WHITESPACE")
    try:
        line = float(line)
    except (TypeError, ValueError):
        return {**base, "status": "REFUSED", "reason": v1.REFUSAL_LINE_INVALID}
    if not math.isfinite(line):
        return {**base, "status": "REFUSED", "reason": v1.REFUSAL_LINE_INVALID}
    if line <= 0:  # also catches -0.0
        return bad("LINE_NONPOSITIVE")
    target = v1._as_date(target_date)
    if target is None:
        return {**base, "status": "REFUSED", "reason": v1.REFUSAL_LINE_INVALID,
                "detail": "TARGET_DATE_UNPARSEABLE"}
    player = store._players.get(str(player_id))
    if player is None:
        return {**base, "status": "REFUSED", "reason": v1.REFUSAL_PLAYER_NOT_IN_STORE}
    priors = _prior(store, player_id, combo, target)
    if len(priors) < v1.MIN_PRIOR_GAMES:
        return {**base, "status": "REFUSED", "reason": v1.REFUSAL_INSUFFICIENT_PRIORS,
                "n_prior": len(priors)}
    pool = _pool(store, player["group"], combo, target)
    src = "POSITION_GROUP"
    if len(pool) < v1.B1_MIN_POOL:
        pool, src = _pool(store, None, combo, target), "LEAGUE_FALLBACK"
    if not pool:
        return {**base, "status": "REFUSED", "reason": v1.REFUSAL_POOL_UNAVAILABLE}
    d = v1.MixtureDistribution(priors, pool)
    return {**base, "status": "PRICED", "player_id": str(player_id), "line": line,
            "target_date": target.isoformat(), "n_prior": len(priors),
            "pool_n": len(pool), "pool_source": src, "model_mean": d.mean(),
            "p_over": d.prob_over(line), "p_push": d.prob_push(line),
            "p_under": d.prob_under(line)}
