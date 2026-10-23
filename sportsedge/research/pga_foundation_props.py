"""PGA research-only hole-by-hole layer on top of ``pga_foundation`` tournament paths.

RESEARCH_ONLY / NO_VALIDATION. Caller-supplied course pars and noise only
(synthetic in tests); no fitting, no backtest, no prices, not wired to RUN IT.

Conservation contract (every hole path):
  * every completed round has exactly 18 integer hole scores whose sum equals
    that round's score in the tournament path (no round is invented or dropped);
  * each hole score is in [1, par + MAX_OVER_PAR] (placeholder guard);
  * score-type counts (eagle-or-better / birdie / par / bogey / double-or-worse)
    partition the 18 holes of each round.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from sportsedge.research.pga_foundation import FoundationError, TournamentPath, check_path

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
HOLES = 18
MAX_OVER_PAR = 6
TYPES = ("EAGLE_OR_BETTER", "BIRDIE", "PAR", "BOGEY", "DOUBLE_OR_WORSE")
PROPS_MARKETS = frozenset({"PLAYER_BIRDIES", "PLAYER_BOGEYS", "HOLE_BIRDIE_OR_BETTER"})


def validate_pars(pars):
    if not isinstance(pars, (list, tuple)) or len(pars) != HOLES:
        raise FoundationError("PGA_COURSE_HOLES_INVALID", repr(pars)[:40])
    for p in pars:
        if isinstance(p, bool) or not isinstance(p, int) or p not in (3, 4, 5):
            raise FoundationError("PGA_PAR_INVALID", repr(p))
    return tuple(pars)


def score_type(score, par):
    d = score - par
    return ("EAGLE_OR_BETTER" if d <= -2 else "BIRDIE" if d == -1 else
            "PAR" if d == 0 else "BOGEY" if d == 1 else "DOUBLE_OR_WORSE")


@dataclass
class HolePath:
    tournament: TournamentPath
    pars: tuple
    holes: dict      # (player_id, round_index) -> tuple of 18 scores

    def counts(self, pid, round_index=None):
        out = {t: 0 for t in TYPES}
        for (p, r), hs in self.holes.items():
            if p == pid and (round_index is None or r == round_index):
                for s, par in zip(hs, self.pars):
                    out[score_type(s, par)] += 1
        return out


def _round_holes(rng, total, pars, swaps):
    lo, hi = [1] * HOLES, [p + MAX_OVER_PAR for p in pars]
    if not sum(lo) <= total <= sum(hi):
        raise FoundationError("PGA_ROUND_SCORE_INFEASIBLE", str(total))
    hs = list(pars)
    for _ in range(swaps):                      # zero-sum noise: +1 one hole, -1 another
        a, b = rng.randrange(HOLES), rng.randrange(HOLES)
        if a != b and hs[a] < hi[a] and hs[b] > lo[b]:
            hs[a] += 1
            hs[b] -= 1
    diff = total - sum(hs)
    step = 1 if diff > 0 else -1
    while diff:
        cand = [i for i in range(HOLES) if (hs[i] < hi[i] if step > 0 else hs[i] > lo[i])]
        i = rng.choice(cand)
        hs[i] += step
        diff -= step
    return tuple(hs)


def simulate_holes(path: TournamentPath, pars, rng: random.Random, *, swaps=4) -> HolePath:
    check_path(path)
    pars = validate_pars(pars)
    if isinstance(swaps, bool) or not isinstance(swaps, int) or swaps < 0:
        raise FoundationError("PGA_INPUT_OUT_OF_RANGE", "swaps")
    if not isinstance(rng, random.Random):
        raise FoundationError("PGA_RNG_REQUIRED")
    holes = {}
    for pid in sorted(path.rounds):
        for r, total in enumerate(path.rounds[pid]):
            holes[(pid, r)] = _round_holes(rng, total, pars, swaps)
    hp = HolePath(path, pars, holes)
    check_holes(hp)
    return hp


def check_holes(hp: HolePath):
    check_path(hp.tournament)
    pars = validate_pars(hp.pars)
    expected = {(p, r) for p, rs in hp.tournament.rounds.items() for r in range(len(rs))}
    if set(hp.holes) != expected:
        raise FoundationError("PGA_HOLE_ROUNDS_MISMATCH")
    for (pid, r), hs in hp.holes.items():
        if not isinstance(hs, tuple) or len(hs) != HOLES:
            raise FoundationError("PGA_HOLE_COUNT_INVALID", f"{pid}:{r}")
        for s, par in zip(hs, pars):
            if isinstance(s, bool) or not isinstance(s, int) or not 1 <= s <= par + MAX_OVER_PAR:
                raise FoundationError("PGA_HOLE_SCORE_INVALID", f"{pid}:{r}:{s!r}")
        if sum(hs) != hp.tournament.rounds[pid][r]:
            raise FoundationError("PGA_HOLES_NOT_CONSERVED", f"{pid}:{r}")
    return True


def settle_prop(hp: HolePath, market: str, *, player_id, line=None, round_index=None,
                hole=None, selection=None):
    check_holes(hp)
    t = hp.tournament
    if player_id not in t.rounds:
        raise FoundationError("PGA_PLAYER_IDENTITY_MISMATCH", str(player_id))
    if round_index is not None and (isinstance(round_index, bool) or not isinstance(round_index, int)
                                    or not 0 <= round_index < 4):
        raise FoundationError("PGA_ROUND_INDEX_INVALID", repr(round_index))
    if t.withdrawn.get(player_id) == 0:
        return "VOID"
    if round_index is not None and round_index >= len(t.rounds[player_id]):
        return "VOID"     # round not played (missed cut / WD): no action
    if market in ("PLAYER_BIRDIES", "PLAYER_BOGEYS"):
        if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
            raise FoundationError("PGA_LINE_NONFINITE", repr(line))
        c = hp.counts(player_id, round_index)
        v = (c["EAGLE_OR_BETTER"] + c["BIRDIE"]) if market == "PLAYER_BIRDIES" \
            else (c["BOGEY"] + c["DOUBLE_OR_WORSE"])
        return "OVER" if v > line else "UNDER" if v < line else "PUSH"
    if market == "HOLE_BIRDIE_OR_BETTER":
        if round_index is None or isinstance(hole, bool) or not isinstance(hole, int) \
                or not 1 <= hole <= HOLES or selection not in ("YES", "NO"):
            raise FoundationError("PGA_SELECTION_IDENTITY_MISMATCH", f"{hole}/{selection}")
        s = hp.holes[(player_id, round_index)][hole - 1]
        return "WIN" if (selection == "YES") == (s < hp.pars[hole - 1]) else "LOSE"
    raise FoundationError("PGA_MARKET_NO_SETTLEMENT", market)
