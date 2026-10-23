"""NFL longest field goal made (research engine, RESEARCH_UNSCREENED).

DK market: LONGEST_FG_MADE (O/U on the kicker's longest made FG, yards).
canonical_coverage resolved this family NO_ENGINE ("no pricing engine
exists anywhere in the repository").  This module builds one on the
already-admitted inputs of NFL_KICKING_EMPIRICAL (nflverse play-by-play
per-(game, kicker) records: fg_attempts [(distance, made)]), reusing that
engine's declared priors and shrinkage constants unchanged.

Construction (strictly point-in-time, same rows as the kicking engine):
    attempts/game  N ~ kicker's shrunk attempt-count PMF (kicking engine)
    per attempt    q(L) = P(made AND distance > L)
                   = [sum_a 1(d_a > L) * r_band(a)
                      + M * sum_b mix_b * r_b * frac_b(L)] / (n_att + M)
                   kicker's own attempt distances, shrunk toward the
                   declared league band mix (uniform within band; the
                   open top band is treated as 60-66 yd, declared).
    P(longest > L) = 1 - sum_n P(N=n) * (1 - q(L))**n
Declared approximation: attempts independent within a game; distance
not conditioned on opponent, weather, venue or game script.

Settlement: a game with NO made FG has no "longest made FG".  DK's
settlement of that case is NOT verified in this repo, so the engine
returns P(at least one made FG longer than L) plus p_no_made_fg
separately and labels settlement_basis UNVERIFIED; it never folds the
no-make mass into either side.

Governance: RESEARCH_UNSCREENED.  Not validated, not registered in the
owner's nfl_family_registry_v2, eligible=false, never PLAY; the
canonical path stays BLOCKED.  No quotes, no EV, no betting authority.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Iterable, Mapping

from sportsedge import nfl_kicking_empirical as k

ENGINE_ID = "NFL_LONGEST_FG_EMPIRICAL"
ENGINE_VERSION = "nfl_longest_fg_empirical_v1_20261022"
GOVERNANCE_STATE = "RESEARCH_UNSCREENED"
TOP_BAND_ASSUMED_MAX = 66.0
LINE_MIN, LINE_MAX = 17.0, 70.0
# Shortest physically possible FG (ball at the 1, +10 end zone, +7 snap).
# The league prior's lowest band is supported on [MIN_FG_DISTANCE, 29].
MIN_FG_DISTANCE = 18.0


class NflLongestFgError(ValueError):
    """Fail-closed error with a machine-readable reason code."""


def _frac_beyond(lo: float, hi: float, line: float) -> float:
    hi = TOP_BAND_ASSUMED_MAX if hi >= 999 else float(hi) + 1.0
    lo = max(float(lo), MIN_FG_DISTANCE)
    if line < lo:
        return 1.0
    if line >= hi:
        return 0.0
    return (hi - line) / (hi - lo)


def price_longest_fg(games: Iterable[Mapping[str, Any]], *, kicker_id: str,
                     kickoff: datetime, line: float) -> dict[str, Any]:
    try:
        line = float(line)
    except (TypeError, ValueError):
        raise NflLongestFgError("LONGEST_FG_LINE_INVALID") from None
    if not math.isfinite(line) or not (LINE_MIN <= line <= LINE_MAX):
        raise NflLongestFgError(f"LONGEST_FG_LINE_OUT_OF_RANGE:{line}")
    if line != math.floor(line) + 0.5:
        # integer lines would need a push rule we have not verified
        raise NflLongestFgError(f"LONGEST_FG_LINE_NOT_HALF_POINT:{line}")
    if line >= TOP_BAND_ASSUMED_MAX:
        # beyond the declared support of the league distance prior
        raise NflLongestFgError(f"LONGEST_FG_LINE_ABOVE_SUPPORT:{line}")
    games = list(games)
    try:
        base = k.estimate_kicking(games, kicker_id=kicker_id, kickoff=kickoff)
    except k.NflKickingError as exc:
        raise NflLongestFgError(f"LONGEST_FG_UPSTREAM:{exc}") from exc
    # Rebuild the exact same PIT window the kicking engine used.
    rows = sorted((g for g in games if g["kickoff"] < kickoff),
                  key=lambda g: g["kickoff"])[-k.TRAILING_GAMES_K:]
    bands = k.DISTANCE_BANDS
    att = [0] * len(bands)
    made = [0] * len(bands)
    dists: list[tuple[float, int]] = []
    for g in rows:
        for d, m in (g.get("fg_attempts") or ()):
            b = k._band_index(d)
            att[b] += 1
            made[b] += 1 if m else 0
            dists.append((float(d), b))
    n_att = len(dists)
    if n_att != base["fg_attempts_used"]:
        raise NflLongestFgError("LONGEST_FG_WINDOW_MISMATCH")
    rates = [(made[i] + k.BAND_SHRINK_ATT * lr) / (att[i] + k.BAND_SHRINK_ATT)
             for i, (_lo, _hi, lr, _lm) in enumerate(bands)]
    mix_total = math.fsum(b[3] for b in bands)

    def q_of(L: float) -> float:
        # per attempt P(made AND distance > L): ONE construction for all
        # three outputs; q_of(-inf) is the per-attempt make probability.
        emp = math.fsum(rates[b] for d, b in dists if d > L)
        lg = math.fsum((lm / mix_total) * rates[i] * _frac_beyond(lo, hi, L)
                       for i, (lo, hi, _lr, lm) in enumerate(bands))
        return (emp + k.MIX_SHRINK_ATT * lg) / (n_att + k.MIX_SHRINK_ATT)

    m = q_of(-math.inf)
    q = q_of(line)
    if not (0.0 < q <= m < 1.0):
        raise NflLongestFgError(f"LONGEST_FG_NO_SUPPORT:{line}")
    # attempt-count PMF: same shrunk construction as the kicking engine
    counts = [len(g.get("fg_attempts") or ()) for g in rows]
    pmf = k._shrunk_count_pmf(counts, k.LEAGUE_FG_ATTEMPT_COUNTS)
    p_no_made = math.fsum(p * (1.0 - m) ** n for n, p in pmf.items())
    p_not_over = (0.0 if q == m else
                  math.fsum(p * ((1.0 - q) ** n - (1.0 - m) ** n)
                            for n, p in pmf.items()))
    p_over = 1.0 - p_no_made - p_not_over
    if not (0.0 < p_over < 1.0):
        raise NflLongestFgError(f"LONGEST_FG_NO_SUPPORT:{line}")
    return {
        "status": "RESEARCH_ONLY", "governance": GOVERNANCE_STATE,
        "validation_status": "NOT_VALIDATED", "eligible": False,
        "engine": ENGINE_ID, "engine_version": ENGINE_VERSION,
        "market": "LONGEST_FG_MADE", "kicker_id": base["kicker_id"],
        "as_of_kickoff": base["as_of_kickoff"], "line": line,
        "games_used": base["games_used"], "fg_attempts_used": n_att,
        "p_made_longer_than_line": p_over,
        "p_made_fg_not_longer_than_line": p_not_over,
        "p_no_made_fg": p_no_made,
        "settlement_basis": "UNVERIFIED_NO_MADE_FG_CASE_NOT_FOLDED",
    }
