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
    # Strokes in an INCOMPLETE round at withdrawal (pid -> int). Recorded
    # separately and never counted as a completed round or in any total.
    partial_round: dict = field(default_factory=dict)
    tournament_id: str | None = None

    def total(self, pid):
        return sum(self.rounds[pid])          # completed rounds only

    def completed_rounds(self, pid):
        return len(self.rounds[pid])

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
    if not isinstance(path.withdrawn, dict):
        raise FoundationError("PGA_WITHDRAWN_ROUND_INVALID", "withdrawn map")
    for pid, wd in path.withdrawn.items():
        if pid not in path.rounds:
            raise FoundationError("PGA_WITHDRAWN_UNKNOWN_PLAYER", str(pid))
        if isinstance(wd, bool) or not isinstance(wd, int) or not 0 <= wd <= 4:
            raise FoundationError("PGA_WITHDRAWN_ROUND_INVALID", f"{pid}:{wd!r}")
        # WD in R1/R2 cannot have made the cut; WD in R3/R4 must have made it.
        if (wd in (1, 2) and pid in path.made_cut) or (wd >= 3 and pid not in path.made_cut):
            raise FoundationError("PGA_WITHDRAWN_CUT_INCONSISTENT", f"{pid}:{wd}")
        # WD during round wd => at most wd-1 COMPLETED rounds (partial round
        # strokes live in partial_round, never in rounds).
        if wd > 0 and len(path.rounds[pid]) > wd - 1:     # wd == 0 handled below
            raise FoundationError("PGA_WITHDRAWN_ROUND_INVALID", f"{pid}: completed rounds >= WD round")
    if not isinstance(path.partial_round, dict):
        raise FoundationError("PGA_PARTIAL_ROUND_INVALID", "partial_round map")
    for pid, st in path.partial_round.items():
        wd = path.withdrawn.get(pid)
        if pid not in path.rounds or not isinstance(wd, int) or wd < 1 \
                or isinstance(st, bool) or not isinstance(st, int) or st < 0:
            raise FoundationError("PGA_PARTIAL_ROUND_INVALID", f"{pid}:{st!r}")
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


_H2H_WD_KINDS = ("WD", "DQ")

# Allowlisted settlement-rule sources (#2352 re-audit). Free text and
# placeholders ("?", "TBD") are refused; jurisdiction/version still pending.
RULE_SOURCE_REGISTRY = {
    "DK_GOLF_SPORT_RULES_CURRENT":
        "https://www.goldennugget.com/lake-charles/casino/draftkings-sportsbook-bar-grill/"
        "draftkings-sportsbook-house-rules/ (Golf > General Golf Settlement Rules)",
    "DK_GNLC_RETAIL_V15":
        "https://lb.goldennugget.com/contentassets/9800d7ef44d6474dad6cd3e69d29dd99/"
        "draftkings-gnlc-retail-house-rules-v15.pdf",
}


def _evidence_bound(path, a, b, evidence):
    """Evidence must name this tournament, exactly these two golfers, a market
    instance, and an allowlisted rule source."""
    if not isinstance(evidence, dict):
        return False
    tid, mid, pids = (evidence.get("tournament_id"), evidence.get("market_instance_id"),
                      evidence.get("player_ids"))
    return (isinstance(path.tournament_id, str) and bool(path.tournament_id)
            and tid == path.tournament_id
            and isinstance(mid, str) and bool(mid.strip())
            and isinstance(pids, (list, tuple)) and len(pids) == 2 and set(pids) == {a, b}
            and evidence.get("rule_source") in RULE_SOURCE_REGISTRY)


def _after_cut_wd_verified(path, wd_pid, evidence, a=None, b=None):
    """True only when every fact the owner ruling (#2352, 2026-10-15) requires
    is present and confirmed: tournament-long H2H market, both teed off, the
    official cut, the exact withdrawal/DQ timing, and a confirmed rule. The rule
    itself is PENDING DraftKings confirmation; WD before teeing off in R3
    (0 holes completed) is never universalised."""
    if not _evidence_bound(path, a, b, evidence):
        return False
    w = evidence.get("withdrawal")
    if not isinstance(w, dict):
        return False
    holes = w.get("holes_completed")
    src = evidence.get("rule_source")
    return (evidence.get("market_type") == "TOURNAMENT_72_H2H"
            and evidence.get("both_teed_off") is True
            and evidence.get("official_cut_confirmed") is True
            and evidence.get("rule_confirmed") is True
            and isinstance(src, str) and bool(src.strip())
            and w.get("player_id") == wd_pid
            and w.get("kind") in _H2H_WD_KINDS
            and w.get("round") == path.withdrawn.get(wd_pid)
            and isinstance(holes, int) and not isinstance(holes, bool)
            and 1 <= holes <= 17)


def _int_ok(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _both_wd_settle(path, player_id, opponent_id, evidence):
    """Both golfers teed off and withdrew/DQ'd (owner ruling #2352, DK current
    Golf Sport Rules): more completed rounds ranks higher; equal -> cumulative
    score after the last fully completed round (partial rounds ignored); equal
    -> ticket tie rule. Every fact must be present and match the path, else
    SETTLEMENT_UNVERIFIED. Neither completing a full round is unresolved."""
    def bad(why):
        raise FoundationError("SETTLEMENT_UNVERIFIED", f"both WD: {why}")
    if not _evidence_bound(path, player_id, opponent_id, evidence):
        bad("evidence not bound to tournament/players/market/allowlisted rule source")
    src = evidence.get("rule_source")
    if not (evidence.get("market_type") == "TOURNAMENT_72_H2H"
            and evidence.get("both_teed_off") is True
            and evidence.get("rule_confirmed") is True
            and isinstance(src, str) and src.strip()):
        bad("market/participation/rule not confirmed")
    ws = evidence.get("withdrawals")
    if not isinstance(ws, dict):
        bad("withdrawals missing")
    rank = {}
    for pid in (player_id, opponent_id):
        w = ws.get(pid)
        if not isinstance(w, dict) or w.get("kind") not in _H2H_WD_KINDS:
            bad(f"{pid} withdrawal record")
        n, sc = w.get("completed_rounds"), w.get("score_after_last_completed")
        rs = path.rounds[pid]
        if not _int_ok(n) or n != len(rs) or w.get("round") != path.withdrawn.get(pid):
            bad(f"{pid} completed rounds/WD round mismatch")
        if n > 0 and (not _int_ok(sc) or sc != sum(rs)):
            bad(f"{pid} score after last completed round mismatch")
        rank[pid] = (n, sc)
    (pn, ps), (on, os_) = rank[player_id], rank[opponent_id]
    if pn == 0 and on == 0:
        bad("neither completed a full round")
    if pn != on:
        return ("WIN", Fraction(1)) if pn > on else ("LOSE", Fraction(1))
    if ps != os_:
        return ("WIN", Fraction(1)) if ps < os_ else ("LOSE", Fraction(1))
    if evidence.get("tie_rule") == "PUSH":
        return ("PUSH", Fraction(1))
    bad("equal score and no confirmed ticket tie rule")


def settle(path: TournamentPath, market: str, *, player_id=None, opponent_id=None, n=None,
           evidence=None):
    """Returns (result, stake_fraction) with result in WIN/LOSE/PUSH/VOID.

    MATCHUP with a golfer who made the cut and then withdrew/was DQ'd raises
    SETTLEMENT_UNVERIFIED unless ``evidence`` confirms every required fact
    (see _after_cut_wd_verified); pending DraftKings confirmation."""
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
        after_cut = [q for q in (player_id, opponent_id)
                     if q in path.withdrawn and q in path.made_cut]
        if pw and ow:
            return _both_wd_settle(path, player_id, opponent_id, evidence)
        if after_cut:
            wq = after_cut[0]
            if not _after_cut_wd_verified(path, wq, evidence, player_id, opponent_id):
                raise FoundationError("SETTLEMENT_UNVERIFIED", f"after-cut WD/DQ {wq}")
            other = opponent_id if wq == player_id else player_id
            wd_wins = other not in path.made_cut      # made cut beats missed cut
            return ("WIN", Fraction(1)) if wd_wins == (wq == player_id) else ("LOSE", Fraction(1))
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
