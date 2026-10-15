"""PGA research-only foundation: coherent 72-hole tournament path + settlement + terminal map.

RESEARCH_ONLY / NO_VALIDATION. Caller-supplied per-round scoring distributions
only (synthetic in tests); no fitting, no backtest, no odds, not wired to RUN IT.

Tournament path contract:
  * every player has 1-4 integer round scores; total == sum of rounds;
  * cut after R2 at top ``cut_top`` and ties (by 36-hole total); only made-cut
    players play R3/R4; withdrawals (WD) stop at the round they withdrew;
  * exactly one winner: ties for first after R4 go to a playoff that yields a
    single winner (no dead heat for the outright winner);
  * finishing positions use standard "T" ties among made-cut finishers.

Settlement conventions:
  * OUTRIGHT: playoff winner only (no dead heat).
  * TOP_N: dead-heat reduction -- if k players tie across the boundary and only
    s places remain inside the top N, the winning stake fraction is s/k.
  * MATCHUP (2-ball, 72-hole H2H): lower total wins when both make the cut;
    a player who makes the cut beats one who misses; equal totals -> PUSH
    (no tie option offered); a WD before teeing off voids; a later WD loses.
  * MAKE_CUT: YES if the player made the cut; a pre-tournament WD voids.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from fractions import Fraction

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
SPORT = "PGA"
TERMINALS = frozenset({
    "VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD", "RESEARCH_ONLY",
    "NO_VALIDATION", "NO_ENGINE", "NO_DATA", "NO_QUOTE", "NO_SETTLEMENT",
    "NOT_OFFERED", "BLOCKED_BY_AUTHORIZATION",
})
_ALLOWED = TERMINALS - {"VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD"}
MIN_ROUND, MAX_ROUND = 55, 100     # impossible-score guard for a par-~72 round


class FoundationError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _num(name, v, *, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FoundationError("PGA_INPUT_NOT_NUMERIC", name)
    if not math.isfinite(v):
        raise FoundationError("PGA_INPUT_NONFINITE", name)
    if v < 0 or (positive and v == 0):
        raise FoundationError("PGA_INPUT_NEGATIVE", name)
    return float(v)


@dataclass(frozen=True)
class PlayerInput:
    player_id: str
    round_mean: float
    round_sd: float
    wd_before_start: bool = False


@dataclass
class TournamentPath:
    rounds: dict                       # player_id -> list[int]
    made_cut: set
    withdrawn: dict = field(default_factory=dict)   # player_id -> round of WD (0 = pre-start)
    winner: str | None = None

    def total(self, pid):
        return sum(self.rounds[pid])

    def positions(self):
        """Standard tied positions among made-cut finishers: pid -> (pos, n_tied)."""
        fin = [p for p in self.made_cut if p not in self.withdrawn]
        out = {}
        for p in fin:
            t = self.total(p)
            better = sum(1 for q in fin if self.total(q) < t)
            tied = sum(1 for q in fin if self.total(q) == t)
            out[p] = (better + 1, tied)
        if self.winner is not None:
            out[self.winner] = (1, 1)
            for p in fin:
                if p != self.winner and out[p][0] == 1:
                    out[p] = (2, out[p][1] - 1)
        return out


def simulate_tournament(players, rng: random.Random, *, cut_top=65) -> TournamentPath:
    if not isinstance(rng, random.Random):
        raise FoundationError("PGA_RNG_REQUIRED")
    if isinstance(cut_top, bool) or not isinstance(cut_top, int) or cut_top < 1:
        raise FoundationError("PGA_CUT_INVALID", repr(cut_top))
    ids = [p.player_id for p in players]
    if not ids or any(not isinstance(i, str) or not i.strip() for i in ids):
        raise FoundationError("PGA_PLAYER_ID_MISSING")
    if len(set(ids)) != len(ids):
        raise FoundationError("PGA_PLAYER_DUPLICATE")
    for p in players:
        _num(f"{p.player_id}.round_mean", p.round_mean, positive=True)
        _num(f"{p.player_id}.round_sd", p.round_sd)

    def score(p):
        s = int(round(rng.gauss(p.round_mean, p.round_sd)))
        return min(MAX_ROUND, max(MIN_ROUND, s))

    path = TournamentPath({p.player_id: [] for p in players}, set())
    active = []
    for p in players:
        if p.wd_before_start:
            path.withdrawn[p.player_id] = 0
        else:
            active.append(p)
    for _ in range(2):
        for p in active:
            path.rounds[p.player_id].append(score(p))
    if not active:
        raise FoundationError("PGA_NO_ACTIVE_FIELD")
    totals = sorted(path.total(p.player_id) for p in active)
    cut_line = totals[min(cut_top, len(totals)) - 1]
    path.made_cut = {p.player_id for p in active if path.total(p.player_id) <= cut_line}
    weekend = [p for p in active if p.player_id in path.made_cut]
    for _ in range(2):
        for p in weekend:
            path.rounds[p.player_id].append(score(p))
    best = min(path.total(p.player_id) for p in weekend)
    leaders = sorted(p.player_id for p in weekend if path.total(p.player_id) == best)
    path.winner = leaders[0] if len(leaders) == 1 else rng.choice(leaders)   # playoff
    check_path(path)
    return path


def check_path(path: TournamentPath):
    for pid, rs in path.rounds.items():
        if not isinstance(rs, list) or len(rs) > 4:
            raise FoundationError("PGA_ROUND_COUNT_INVALID", pid)
        for s in rs:
            if isinstance(s, bool) or not isinstance(s, int) or not MIN_ROUND <= s <= MAX_ROUND:
                raise FoundationError("PGA_ROUND_SCORE_INVALID", f"{pid}:{s!r}")
        wd = path.withdrawn.get(pid)
        if wd == 0 and rs:
            raise FoundationError("PGA_PRESTART_WD_HAS_SCORES", pid)
        if pid in path.made_cut:
            if len(rs) < 2:
                raise FoundationError("PGA_MADE_CUT_WITHOUT_36_HOLES", pid)
            if wd is None and len(rs) != 4:
                raise FoundationError("PGA_FINISHER_ROUND_COUNT", pid)
        elif wd is None and len(rs) != 2:
            raise FoundationError("PGA_MISSED_CUT_PLAYED_WEEKEND", pid)
    if not path.made_cut <= set(path.rounds):
        raise FoundationError("PGA_PLAYER_IDENTITY_MISMATCH", "made_cut")
    # cut coherence: nobody who missed beats anyone who made it through 36 holes
    made36 = [sum(path.rounds[p][:2]) for p in path.made_cut]
    missed36 = [sum(r[:2]) for p, r in path.rounds.items()
                if p not in path.made_cut and len(r) >= 2 and p not in path.withdrawn]
    if made36 and missed36 and min(missed36) <= max(made36):
        raise FoundationError("PGA_CUT_INCOHERENT")
    fin = [p for p in path.made_cut if p not in path.withdrawn]
    if path.winner not in fin:
        raise FoundationError("PGA_WINNER_IDENTITY_MISMATCH", str(path.winner))
    if path.total(path.winner) != min(path.total(p) for p in fin):
        raise FoundationError("PGA_WINNER_NOT_LOW_SCORE", path.winner)
    return True


def settle(path: TournamentPath, market: str, *, player_id=None, opponent_id=None, n=None):
    """Returns (result, stake_fraction) with result in WIN/LOSE/PUSH/VOID."""
    check_path(path)
    if player_id not in path.rounds:
        raise FoundationError("PGA_PLAYER_IDENTITY_MISMATCH", str(player_id))
    if path.withdrawn.get(player_id) == 0 and market != "OUTRIGHT":
        return ("VOID", Fraction(1))
    pos = path.positions()
    if market == "OUTRIGHT":
        if path.withdrawn.get(player_id) == 0:
            return ("VOID", Fraction(1))
        return ("WIN", Fraction(1)) if player_id == path.winner else ("LOSE", Fraction(1))
    if market == "TOP_N":
        if isinstance(n, bool) or not isinstance(n, int) or n < 1:
            raise FoundationError("PGA_TOP_N_INVALID", repr(n))
        if player_id not in pos:
            return ("LOSE", Fraction(1))
        p, tied = pos[player_id]
        if p > n:
            return ("LOSE", Fraction(1))
        if p + tied - 1 <= n:
            return ("WIN", Fraction(1))
        return ("WIN", Fraction(n - p + 1, tied))          # dead heat
    if market == "MAKE_CUT":
        return ("WIN", Fraction(1)) if player_id in path.made_cut else ("LOSE", Fraction(1))
    if market == "MATCHUP":
        if opponent_id not in path.rounds or opponent_id == player_id:
            raise FoundationError("PGA_PLAYER_IDENTITY_MISMATCH", str(opponent_id))
        if path.withdrawn.get(opponent_id) == 0:
            return ("VOID", Fraction(1))
        pw, ow = player_id in path.withdrawn, opponent_id in path.withdrawn
        if pw and ow:
            return ("VOID", Fraction(1))
        if pw or ow:
            return ("LOSE", Fraction(1)) if pw else ("WIN", Fraction(1))
        pc, oc = player_id in path.made_cut, opponent_id in path.made_cut
        if pc != oc:
            return ("WIN", Fraction(1)) if pc else ("LOSE", Fraction(1))
        a, b = path.total(player_id), path.total(opponent_id)
        if a == b:
            return ("PUSH", Fraction(1))
        return ("WIN", Fraction(1)) if a < b else ("LOSE", Fraction(1))
    raise FoundationError("PGA_MARKET_NO_SETTLEMENT", market)


_SIM = "per-round score skeleton + settlement; caller-supplied distributions, no fit, no backtest"
MARKET_TERMINALS = {
    "OUTRIGHT": ("RESEARCH_ONLY", _SIM),
    "TOP_N": ("RESEARCH_ONLY", _SIM + "; dead-heat encoded"),
    "MAKE_CUT": ("RESEARCH_ONLY", _SIM),
    "MATCHUP": ("RESEARCH_ONLY", _SIM),
    "ROUND_SCORE": ("NO_SETTLEMENT", "round over/under settlement not encoded"),
    "THREE_BALL": ("NO_SETTLEMENT", "3-ball dead-heat rules not encoded"),
    "FIRST_ROUND_LEADER": ("NO_SETTLEMENT", "FRL dead-heat rules not encoded"),
    "HOLE_PROPS": ("RESEARCH_ONLY", _SIM + "; hole layer: birdie-or-better per hole"),
    "BIRDIES_PROPS": ("RESEARCH_ONLY", _SIM + "; hole layer: birdie/bogey counts"),
    "NATIONALITY_SPECIALS": ("NOT_OFFERED", "specials out of scope"),
}
for _m, (_t, _r) in MARKET_TERMINALS.items():
    assert _t in _ALLOWED, (_m, _t)


def market_terminal(market: str):
    t, reason = MARKET_TERMINALS.get(market, ("NO_ENGINE", "market not inventoried"))
    return {"sport": SPORT, "market": market, "terminal": t, "reason": reason,
            "validation": VALIDATION, "probability": None, "price": None, "ev": None}
