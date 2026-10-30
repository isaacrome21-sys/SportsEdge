"""UFC research-only foundation: coherent bout path + settlement + terminal map.

RESEARCH_ONLY / NO_VALIDATION. Caller-supplied hazards only (synthetic in tests);
no fitting, no backtest, no odds, not wired to RUN IT, no activation.

Bout path contract:
  * scheduled rounds are 3 or 5, five minutes each;
  * exactly one result: a finish (KO_TKO / SUBMISSION / DQ) by one fighter at a
    round and time inside that round, or a decision after the final round
    (UNANIMOUS / SPLIT / MAJORITY for a winner, or DRAW), or NO_CONTEST;
  * a finish ends the bout: no later round is fought.

Settlement conventions (sportsbook-standard, encoded explicitly):
  * MONEYLINE: DRAW -> PUSH (two-way, no draw option); NO_CONTEST -> VOID.
  * NO_CONTEST voids every market on the bout.
  * METHOD_OF_VICTORY: KO_TKO and DQ settle together as KO/TKO/DQ; decision
    types collapse to DECISION; DRAW (incl. TECHNICAL_DRAW) -> LOSE for every
    fighter-specific selection; an offered "DRAW" selection (draw_offered=True)
    WINS on a draw and LOSES otherwise (owner ruling #2351, 2026-10-15).
  * TOTAL_ROUNDS x.5: the half point is 2:30 of round ceil(x); a finish at
    exactly 2:30 of that round settles OVER.
  * GOES_THE_DISTANCE: YES for any decision, including DRAW.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

STATUS = "RESEARCH_ONLY"
VALIDATION = "NO_VALIDATION"
SPORT = "UFC"
TERMINALS = frozenset({
    "VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD", "RESEARCH_ONLY",
    "NO_VALIDATION", "NO_ENGINE", "NO_DATA", "NO_QUOTE", "NO_SETTLEMENT",
    "NOT_OFFERED", "BLOCKED_BY_AUTHORIZATION",
})
_ALLOWED = TERMINALS - {"VERIFIED_EDGE_ELIGIBLE", "VALIDATED_FOR_FORWARD"}
ROUND_SEC = 300
FINISH_METHODS = ("KO_TKO", "SUBMISSION", "DQ")
DECISION_METHODS = ("UNANIMOUS", "SPLIT", "MAJORITY")
DRAW_METHODS = ("DRAW", "TECHNICAL_DRAW")   # a technical draw IS a draw
ALL_METHODS = FINISH_METHODS + DECISION_METHODS + DRAW_METHODS + ("NO_CONTEST",)


class FoundationError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _num(name, v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FoundationError("UFC_INPUT_NOT_NUMERIC", name)
    if not math.isfinite(v):
        raise FoundationError("UFC_INPUT_NONFINITE", name)
    if v < 0:
        raise FoundationError("UFC_INPUT_NEGATIVE", name)
    return float(v)


@dataclass(frozen=True)
class FighterInput:
    fighter_id: str
    ko_per_round: float        # hazard of winning by KO/TKO in a 5-minute round
    sub_per_round: float       # hazard of winning by submission in a round
    decision_weight: float     # relative weight in a judges' decision (> 0)

    def validate(self):
        if not isinstance(self.fighter_id, str) or not self.fighter_id.strip():
            raise FoundationError("UFC_FIGHTER_ID_MISSING")
        for k in ("ko_per_round", "sub_per_round", "decision_weight"):
            _num(f"{self.fighter_id}.{k}", getattr(self, k))
        if self.decision_weight == 0:
            raise FoundationError("UFC_DECISION_WEIGHT_ZERO", self.fighter_id)


@dataclass(frozen=True)
class BoutPath:
    red_id: str
    blue_id: str
    scheduled_rounds: int
    method: str
    winner: str | None       # None for DRAW / NO_CONTEST
    end_round: int
    end_second: int          # seconds elapsed in end_round (ROUND_SEC for decisions)

    @property
    def elapsed_seconds(self):
        return (self.end_round - 1) * ROUND_SEC + self.end_second


def check_bout(b: BoutPath):
    if not _int(b.scheduled_rounds) or b.scheduled_rounds not in (3, 5):
        raise FoundationError("UFC_SCHEDULED_ROUNDS_INVALID", str(b.scheduled_rounds))
    if not b.red_id or not b.blue_id or b.red_id == b.blue_id:
        raise FoundationError("UFC_FIGHTER_IDENTITY_COLLISION")
    if b.method not in ALL_METHODS:
        raise FoundationError("UFC_METHOD_INVALID", str(b.method))
    if not _int(b.end_round) or not 1 <= b.end_round <= b.scheduled_rounds:
        raise FoundationError("UFC_ROUND_INVALID", str(b.end_round))
    if not _int(b.end_second) or not 0 < b.end_second <= ROUND_SEC:
        raise FoundationError("UFC_TIME_INVALID", str(b.end_second))
    if b.method in FINISH_METHODS:
        if b.winner not in (b.red_id, b.blue_id):
            raise FoundationError("UFC_WINNER_IDENTITY_MISMATCH", str(b.winner))
    elif b.method == "TECHNICAL_DRAW":
        if b.winner is not None:
            raise FoundationError("UFC_DRAW_WITH_WINNER")
    elif b.method in DECISION_METHODS or b.method == "DRAW":
        if b.end_round != b.scheduled_rounds or b.end_second != ROUND_SEC:
            raise FoundationError("UFC_DECISION_BEFORE_FINAL_BELL")
        if b.method == "DRAW":
            if b.winner is not None:
                raise FoundationError("UFC_DRAW_WITH_WINNER")
        elif b.winner not in (b.red_id, b.blue_id):
            raise FoundationError("UFC_WINNER_IDENTITY_MISMATCH", str(b.winner))
    elif b.winner is not None:       # NO_CONTEST
        raise FoundationError("UFC_NO_CONTEST_WITH_WINNER")
    return True


def simulate_bout(red: FighterInput, blue: FighterInput, rng: random.Random, *,
                  scheduled_rounds=3, draw_prob=0.01) -> BoutPath:
    red.validate()
    blue.validate()
    if red.fighter_id == blue.fighter_id:
        raise FoundationError("UFC_FIGHTER_IDENTITY_COLLISION", red.fighter_id)
    if scheduled_rounds not in (3, 5):
        raise FoundationError("UFC_SCHEDULED_ROUNDS_INVALID", str(scheduled_rounds))
    _num("draw_prob", draw_prob)
    if draw_prob >= 1:
        raise FoundationError("UFC_INPUT_OUT_OF_RANGE", "draw_prob")
    if not isinstance(rng, random.Random):
        raise FoundationError("UFC_RNG_REQUIRED")
    hazards = [(red.fighter_id, "KO_TKO", red.ko_per_round),
               (red.fighter_id, "SUBMISSION", red.sub_per_round),
               (blue.fighter_id, "KO_TKO", blue.ko_per_round),
               (blue.fighter_id, "SUBMISSION", blue.sub_per_round)]
    total = sum(h for *_, h in hazards)
    if total >= 1:
        raise FoundationError("UFC_INPUT_OUT_OF_RANGE", "per-round finish hazard >= 1")
    for rnd in range(1, scheduled_rounds + 1):
        if rng.random() < total:
            r = rng.random() * total
            for fid, method, h in hazards:
                r -= h
                if r <= 0:
                    break
            sec = 1 + int(rng.random() * ROUND_SEC)
            b = BoutPath(red.fighter_id, blue.fighter_id, scheduled_rounds, method,
                         fid, rnd, min(sec, ROUND_SEC))
            check_bout(b)
            return b
    if rng.random() < draw_prob:
        b = BoutPath(red.fighter_id, blue.fighter_id, scheduled_rounds, "DRAW", None,
                     scheduled_rounds, ROUND_SEC)
    else:
        wr = red.decision_weight / (red.decision_weight + blue.decision_weight)
        winner = red.fighter_id if rng.random() < wr else blue.fighter_id
        u = rng.random()
        kind = "UNANIMOUS" if u < 0.7 else "SPLIT" if u < 0.92 else "MAJORITY"
        b = BoutPath(red.fighter_id, blue.fighter_id, scheduled_rounds, kind, winner,
                     scheduled_rounds, ROUND_SEC)
    check_bout(b)
    return b


def _line(line):
    if isinstance(line, bool) or not isinstance(line, (int, float)) or not math.isfinite(line):
        raise FoundationError("UFC_LINE_NONFINITE", repr(line))
    if line <= 0 or (line * 2) % 2 != 1:
        raise FoundationError("UFC_ROUNDS_LINE_NOT_HALF", repr(line))
    return line


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _validate_request(b, market, selection, line, round_no, draw_offered=False):
    """Validate market identity, selection and line BEFORE any VOID/settle."""
    fighters = (b.red_id, b.blue_id)
    if market == "ROUND_BETTING":
        # Owner ruling 2026-10-15: no generic round-betting rule; the exact
        # DK market (FIGHTER_TO_WIN_IN_ROUND, WIN_AND_TOTAL_ROUNDS) governs.
        raise FoundationError("UFC_MARKET_AMBIGUOUS", market)
    if market == "MONEYLINE":
        if selection not in fighters:
            raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", str(selection))
    elif market == "METHOD_OF_VICTORY":
        if selection == "DRAW":
            if draw_offered is not True:
                raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", "DRAW not offered")
            return
        fid, how = selection if isinstance(selection, tuple) and len(selection) == 2 else (None, None)
        if fid not in fighters or how not in ("KO_TKO_DQ", "SUBMISSION", "DECISION"):
            raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", repr(selection))
    elif market == "FIGHTER_TO_WIN_IN_ROUND":
        if selection not in fighters or not _int(round_no) \
                or not 1 <= round_no <= b.scheduled_rounds:
            raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", f"{selection}/{round_no}")
    elif market in ("TOTAL_ROUNDS", "WIN_AND_TOTAL_ROUNDS"):
        ln = _line(line)
        if ln >= b.scheduled_rounds:
            raise FoundationError("UFC_ROUNDS_LINE_OUT_OF_RANGE", repr(line))
        if market == "WIN_AND_TOTAL_ROUNDS":
            fid, ou = selection if isinstance(selection, tuple) and len(selection) == 2 else (None, None)
            if fid not in fighters or ou not in ("OVER", "UNDER"):
                raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", repr(selection))
    elif market == "GOES_THE_DISTANCE":
        if selection not in ("YES", "NO"):
            raise FoundationError("UFC_SELECTION_IDENTITY_MISMATCH", str(selection))
    else:
        raise FoundationError("UFC_MARKET_NO_SETTLEMENT", market)


def _total_rounds(b, line):
    threshold = int(math.floor(line)) * ROUND_SEC + ROUND_SEC // 2
    return "OVER" if b.elapsed_seconds >= threshold else "UNDER"


def _no_contest(b, market, selection, line, round_no):
    """NO_CONTEST voids only markets NOT already decided before the stoppage
    (#2351 re-audit). Decided outcomes settle; undecided ones VOID."""
    if market == "TOTAL_ROUNDS":
        return "OVER" if _total_rounds(b, line) == "OVER" else "VOID"
    if market == "FIGHTER_TO_WIN_IN_ROUND":
        return "LOSE" if round_no < b.end_round else "VOID"   # round passed with no win
    if market == "WIN_AND_TOTAL_ROUNDS":
        _, ou = selection
        return "LOSE" if ou == "UNDER" and _total_rounds(b, line) == "OVER" else "VOID"
    return "VOID"   # MONEYLINE / METHOD_OF_VICTORY / GOES_THE_DISTANCE: undecided


def settle(b: BoutPath, market: str, *, selection=None, line=None, round_no=None,
           draw_offered=False):
    """Settle by EXACT market identity (DK house rules v15 MMA, owner ruling
    2026-10-15 on #2351; jurisdiction/version still to be confirmed):
      * MONEYLINE (two-way, no draw option): DRAW -> PUSH.
      * FIGHTER_TO_WIN_IN_ROUND: DRAW -> LOSE (no fighter won in that round).
      * WIN_AND_TOTAL_ROUNDS (fighter to win + over/under rounds): DRAW -> LOSE.
      * TOTAL_ROUNDS: actual elapsed time, draws included.
      * NO_CONTEST: after validation, already-decided outcomes settle
        (e.g. Over 1.5 passed at R2 2:30); undecided markets VOID.
    """
    check_bout(b)
    _validate_request(b, market, selection, line, round_no, draw_offered)
    if b.method == "NO_CONTEST":
        return _no_contest(b, market, selection, line, round_no)
    draw = b.method in DRAW_METHODS
    if market == "MONEYLINE":
        if draw:
            return "PUSH"
        return "WIN" if selection == b.winner else "LOSE"
    if market == "METHOD_OF_VICTORY":
        if selection == "DRAW":
            return "WIN" if draw else "LOSE"
        if draw:
            return "LOSE"   # no fighter won by any method (owner ruling #2351)
        fid, how = selection
        got = ("KO_TKO_DQ" if b.method in ("KO_TKO", "DQ") else
               "SUBMISSION" if b.method == "SUBMISSION" else "DECISION")
        return "WIN" if (fid, how) == (b.winner, got) else "LOSE"
    if market == "FIGHTER_TO_WIN_IN_ROUND":
        finished = b.method in FINISH_METHODS
        return "WIN" if finished and b.winner == selection and b.end_round == round_no else "LOSE"
    if market == "TOTAL_ROUNDS":
        return _total_rounds(b, line)
    if market == "WIN_AND_TOTAL_ROUNDS":
        if draw:
            return "LOSE"
        fid, ou = selection
        return "WIN" if fid == b.winner and _total_rounds(b, line) == ou else "LOSE"
    if market == "GOES_THE_DISTANCE":
        went = b.method in DECISION_METHODS or b.method == "DRAW"   # technical draw ends early
        return "WIN" if (selection == "YES") == went else "LOSE"
    raise FoundationError("UFC_MARKET_NO_SETTLEMENT", market)


_SIM = "per-round hazard skeleton + settlement; caller-supplied hazards, no fit, no backtest"
MARKET_TERMINALS = {
    "MONEYLINE": ("RESEARCH_ONLY", _SIM),
    "METHOD_OF_VICTORY": ("RESEARCH_ONLY", _SIM),
    "ROUND_BETTING": ("NO_SETTLEMENT", "generic round betting refused; use exact DK market"),
    "FIGHTER_TO_WIN_IN_ROUND": ("RESEARCH_ONLY", _SIM + "; draw -> LOSE per DK v15"),
    "WIN_AND_TOTAL_ROUNDS": ("RESEARCH_ONLY", _SIM + "; draw -> LOSE per DK v15"),
    "TOTAL_ROUNDS": ("RESEARCH_ONLY", _SIM),
    "GOES_THE_DISTANCE": ("RESEARCH_ONLY", _SIM),
    "DRAW_3WAY": ("NO_SETTLEMENT", "3-way draw market settlement not encoded"),
    "SIGNIFICANT_STRIKES": ("RESEARCH_ONLY", _SIM + "; stats layer, exposure-scaled to the finish"),
    "TAKEDOWNS": ("RESEARCH_ONLY", _SIM + "; stats layer, landed <= attempts"),
    "KNOCKDOWNS": ("RESEARCH_ONLY", _SIM + "; stats layer, KD <= landed strikes"),
    "FIGHT_OF_THE_NIGHT": ("NOT_OFFERED", "award markets out of scope"),
}
for _m, (_t, _r) in MARKET_TERMINALS.items():
    assert _t in _ALLOWED, (_m, _t)


def market_terminal(market: str):
    t, reason = MARKET_TERMINALS.get(market, ("NO_ENGINE", "market not inventoried"))
    return {"sport": SPORT, "market": market, "terminal": t, "reason": reason,
            "validation": VALIDATION, "probability": None, "price": None, "ev": None}
