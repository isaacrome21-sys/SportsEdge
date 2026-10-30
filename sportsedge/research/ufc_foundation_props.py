"""UFC research-only fight-stat layer on top of ``ufc_foundation`` bout paths.

RESEARCH_ONLY / NO_VALIDATION. Caller-supplied per-minute rates only (synthetic in
tests); no fitting, no backtest, no prices, not wired to RUN IT, no activation.

Consistency contract (every stats path):
  * stats exist only for rounds actually fought (1..end_round); the final round's
    exposure is end_second / 300, so a 0:30 finish cannot carry a full round of
    output; per-round stats sum to fight totals;
  * knockdowns by a fighter in a round <= that fighter's significant strikes
    landed in that round; takedowns landed <= takedown attempts;
  * a KO/TKO winner landed at least one significant strike in the final round;
  * all counts are nonnegative integers.
Settlement: per-fighter O/U on SIGNIFICANT_STRIKES / TAKEDOWNS / KNOCKDOWNS for the
whole fight; NO_CONTEST voids (matching the bout-level rule).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from sportsedge.research.ufc_foundation import (ROUND_SEC, BoutPath, FoundationError,
                                                _num, check_bout)

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
STATS = ("SIG", "TD", "TDA", "KD")
MARKET_STAT = {"SIGNIFICANT_STRIKES": "SIG", "TAKEDOWNS": "TD", "KNOCKDOWNS": "KD"}
PROPS_MARKETS = frozenset(MARKET_STAT)


@dataclass(frozen=True)
class FighterStatsInput:
    fighter_id: str
    sig_per_min: float
    td_att_per15: float
    td_acc: float           # in [0, 1]
    kd_per_sig: float       # in [0, 1]

    def validate(self):
        if not isinstance(self.fighter_id, str) or not self.fighter_id.strip():
            raise FoundationError("UFC_FIGHTER_ID_MISSING")
        for k in ("sig_per_min", "td_att_per15", "td_acc", "kd_per_sig"):
            _num(f"{self.fighter_id}.{k}", getattr(self, k))
        if self.td_acc > 1 or self.kd_per_sig > 1:
            raise FoundationError("UFC_INPUT_OUT_OF_RANGE", self.fighter_id)


@dataclass
class StatsPath:
    bout: BoutPath
    rounds: dict    # (fighter_id, round_no) -> {"SIG":, "TD":, "TDA":, "KD":}

    def total(self, fid, stat):
        return sum(v[stat] for (f, _), v in self.rounds.items() if f == fid)


def _poisson(rng, lam):
    if lam <= 0:
        return 0
    if lam > 60:
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def _binom(rng, n, p):
    return sum(1 for _ in range(n) if rng.random() < p)


def simulate_stats(bout: BoutPath, red: FighterStatsInput, blue: FighterStatsInput,
                   rng: random.Random) -> StatsPath:
    check_bout(bout)
    red.validate()
    blue.validate()
    if (red.fighter_id, blue.fighter_id) != (bout.red_id, bout.blue_id):
        raise FoundationError("UFC_STATS_IDENTITY_MISMATCH", f"{red.fighter_id}/{blue.fighter_id}")
    if not isinstance(rng, random.Random):
        raise FoundationError("UFC_RNG_REQUIRED")
    rounds = {}
    for rnd in range(1, bout.end_round + 1):
        expo = (bout.end_second if rnd == bout.end_round else ROUND_SEC) / ROUND_SEC
        for f in (red, blue):
            sig = _poisson(rng, f.sig_per_min * 5 * expo)
            if (bout.method == "KO_TKO" and f.fighter_id == bout.winner
                    and rnd == bout.end_round and sig == 0):
                sig = 1                     # a KO/TKO requires landed strikes
            tda = _poisson(rng, f.td_att_per15 / 3 * expo)
            rounds[(f.fighter_id, rnd)] = {"SIG": sig, "TD": _binom(rng, tda, f.td_acc),
                                           "TDA": tda, "KD": _binom(rng, sig, f.kd_per_sig)}
    path = StatsPath(bout, rounds)
    check_stats(path)
    return path


def check_stats(path: StatsPath):
    b = path.bout
    check_bout(b)
    fighters = (b.red_id, b.blue_id)
    expected = {(f, r) for f in fighters for r in range(1, b.end_round + 1)}
    if set(path.rounds) != expected:
        bad = set(path.rounds) - expected
        raise FoundationError("UFC_STATS_ROUND_NOT_FOUGHT" if bad else
                              "UFC_STATS_ROUND_MISSING", repr(sorted(bad or expected)[:1]))
    for key, v in path.rounds.items():
        if set(v) != set(STATS):
            raise FoundationError("UFC_STATS_FIELDS_INVALID", repr(key))
        for s in STATS:
            x = v[s]
            if isinstance(x, bool) or not isinstance(x, int) or x < 0:
                raise FoundationError("UFC_STATS_COUNT_INVALID", f"{key}:{s}")
        if v["KD"] > v["SIG"]:
            raise FoundationError("UFC_KNOCKDOWNS_EXCEED_STRIKES", repr(key))
        if v["TD"] > v["TDA"]:
            raise FoundationError("UFC_TAKEDOWNS_EXCEED_ATTEMPTS", repr(key))
    if b.method == "KO_TKO" and path.rounds[(b.winner, b.end_round)]["SIG"] < 1:
        raise FoundationError("UFC_KO_WITHOUT_STRIKE")
    return True


def settle_stat(path: StatsPath, market: str, *, fighter_id, line, side=None):
    """O/U on a fighter stat. NO_CONTEST (#2351 re-audit): a line already
    reached before the stoppage is decided -> OVER (and an UNDER ticket LOSEs);
    a line not yet reached is VOID."""
    check_stats(path)
    if market not in MARKET_STAT:
        raise FoundationError("UFC_MARKET_NO_SETTLEMENT", market)
    if fighter_id not in (path.bout.red_id, path.bout.blue_id):
        raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", str(fighter_id))
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise FoundationError("UFC_LINE_NONFINITE", repr(line))
    if side not in (None, "OVER", "UNDER"):
        raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", repr(side))
    v = path.total(fighter_id, MARKET_STAT[market])
    if path.bout.method == "NO_CONTEST":
        if v > line:
            return "LOSE" if side == "UNDER" else "OVER"
        return "VOID"
    return "OVER" if v > line else "UNDER" if v < line else "PUSH"
