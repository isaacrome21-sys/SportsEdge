"""One grader interface + no-vig CLV for every sport.

``grade`` settles a pick from a final score or a final stat value. Sport code
only supplies the numbers (scores, or the player's stat); settlement rules are
shared: moneyline / spread / total / team_total / prop / yes_no.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .picks import PickRecord, american_to_decimal

WIN, LOSS, PUSH = "WIN", "LOSS", "PUSH"
_EPS = 1e-9


class GradeError(ValueError):
    pass


@dataclass(frozen=True)
class FinalResult:
    away_score: float | None = None
    home_score: float | None = None
    stat: float | None = None          # player stat / team total / first-inning runs
    occurred: bool | None = None       # yes/no markets (e.g. first HR, anytime TD)


def _cmp(value: float, line: float, positive: str) -> str:
    if abs(value - line) < _EPS:
        return PUSH
    return WIN if (value > line) == (positive == "OVER") else LOSS


def grade(pick: PickRecord | Mapping, result: FinalResult, *, family: str) -> str:
    sel = (pick.selection if isinstance(pick, PickRecord) else pick["selection"]).upper()
    line = pick.line if isinstance(pick, PickRecord) else pick.get("line")
    if family in {"moneyline", "spread"}:
        if result.away_score is None or result.home_score is None:
            raise GradeError("GRADE_SCORE_MISSING")
        if sel not in {"AWAY", "HOME"}:
            raise GradeError(f"GRADE_SELECTION_INVALID:{sel}")
        mine = result.away_score if sel == "AWAY" else result.home_score
        theirs = result.home_score if sel == "AWAY" else result.away_score
        handicap = 0.0
        if family == "spread":
            if line is None:
                raise GradeError("GRADE_LINE_MISSING")
            handicap = float(line)          # line is the SELECTED side's handicap
        margin = mine + handicap - theirs
        if abs(margin) < _EPS:
            return PUSH
        return WIN if margin > 0 else LOSS
    if family == "total":
        if result.away_score is None or result.home_score is None or line is None:
            raise GradeError("GRADE_SCORE_OR_LINE_MISSING")
        return _cmp(result.away_score + result.home_score, float(line), sel)
    if family in {"team_total", "prop"}:
        if result.stat is None or line is None:
            raise GradeError("GRADE_STAT_OR_LINE_MISSING")
        return _cmp(float(result.stat), float(line), sel)
    if family == "yes_no":
        if line is not None and result.stat is not None:
            return _cmp(float(result.stat), float(line), sel)
        if result.occurred is None:
            raise GradeError("GRADE_OCCURRED_MISSING")
        return WIN if result.occurred == (sel in {"YES", "OVER"}) else LOSS
    raise GradeError(f"GRADE_FAMILY_UNKNOWN:{family}")


def units(outcome: str, dk_price: int, stake: float = 1.0) -> float:
    if outcome == WIN:
        return stake * (american_to_decimal(dk_price) - 1)
    if outcome == LOSS:
        return -stake
    return 0.0


def no_vig_probability(price: int, opposite: int) -> float:
    """Multiplicative (proportional) de-vig of a two-sided pair."""
    a = 1 / american_to_decimal(price)
    b = 1 / american_to_decimal(opposite)
    return a / (a + b)


def no_vig_clv(entry_price: int, entry_opposite: int, close_price: int, close_opposite: int,
               *, entry_line: float | None = None, close_line: float | None = None) -> float:
    """CLV = close no-vig p(selected side) - entry no-vig p(selected side).

    Probabilities at different lines are not comparable: a moved line fails
    closed instead of reporting a number.
    """
    if (entry_line is None) != (close_line is None) or (
            entry_line is not None and abs(float(entry_line) - float(close_line)) > _EPS):
        raise GradeError(f"CLV_LINE_MOVED:{entry_line}->{close_line}")
    return no_vig_probability(close_price, close_opposite) - no_vig_probability(entry_price, entry_opposite)
