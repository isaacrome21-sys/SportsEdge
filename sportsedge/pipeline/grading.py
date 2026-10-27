"""One grader interface + no-vig CLV for every sport.

``grade`` settles a pick from a final score or a final stat value. Sport code
only supplies the numbers (scores, or the player's stat); settlement rules are
shared: moneyline / spread / total / team_total / prop / yes_no.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from math import isfinite
from numbers import Real

from .picks import PickRecord, american_to_decimal

WIN, LOSS, PUSH = "WIN", "LOSS", "PUSH"
_EPS = 1e-9


class GradeError(ValueError):
    pass


def _real(value: object, name: str, *, nonnegative: bool = False) -> float:
    """Provider finals/lines cannot admit NaN, infinity, bool or coercible text."""
    if not isinstance(value, Real) or isinstance(value, bool):
        raise GradeError(f"GRADE_{name}_INVALID")
    try:
        number = float(value)
    except (OverflowError, ValueError) as exc:
        raise GradeError(f"GRADE_{name}_INVALID") from exc
    if not isfinite(number) or (nonnegative and number < 0):
        raise GradeError(f"GRADE_{name}_INVALID")
    return number


@dataclass(frozen=True)
class FinalResult:
    away_score: float | None = None
    home_score: float | None = None
    stat: float | None = None          # player stat / team total / first-inning runs
    occurred: bool | None = None       # yes/no markets (e.g. first HR, anytime TD)


def _finite_derived(value: float, name: str) -> float:
    """Reject overflow from individually finite settlement inputs."""
    if not isfinite(value):
        raise GradeError(f"GRADE_{name}_INVALID")
    return value


def _cmp(value: float, line: float, positive: str) -> str:
    if positive not in {"OVER", "UNDER"}:
        raise GradeError(f"GRADE_SELECTION_INVALID:{positive}")
    delta = _finite_derived(value - line, "DELTA")
    if abs(delta) < _EPS:
        return PUSH
    return WIN if (value > line) == (positive == "OVER") else LOSS


def grade(pick: PickRecord | Mapping, result: FinalResult, *, family: str) -> str:
    selection = pick.selection if isinstance(pick, PickRecord) else pick["selection"]
    if not isinstance(selection, str) or not selection.strip():
        raise GradeError("GRADE_SELECTION_INVALID")
    sel = selection.upper()
    line = pick.line if isinstance(pick, PickRecord) else pick.get("line")
    if family in {"moneyline", "spread"}:
        if result.away_score is None or result.home_score is None:
            raise GradeError("GRADE_SCORE_MISSING")
        if sel not in {"AWAY", "HOME"}:
            raise GradeError(f"GRADE_SELECTION_INVALID:{sel}")
        away = _real(result.away_score, "AWAY_SCORE", nonnegative=True)
        home = _real(result.home_score, "HOME_SCORE", nonnegative=True)
        mine = away if sel == "AWAY" else home
        theirs = home if sel == "AWAY" else away
        handicap = 0.0
        if family == "spread":
            if line is None:
                raise GradeError("GRADE_LINE_MISSING")
            handicap = _real(line, "LINE")  # line is the SELECTED side's handicap
        subtotal = _finite_derived(mine + handicap, "MARGIN")
        margin = _finite_derived(subtotal - theirs, "MARGIN")
        if abs(margin) < _EPS:
            return PUSH
        return WIN if margin > 0 else LOSS
    if family == "total":
        if result.away_score is None or result.home_score is None or line is None:
            raise GradeError("GRADE_SCORE_OR_LINE_MISSING")
        away = _real(result.away_score, "AWAY_SCORE", nonnegative=True)
        home = _real(result.home_score, "HOME_SCORE", nonnegative=True)
        total = _finite_derived(away + home, "TOTAL")
        return _cmp(total, _real(line, "LINE"), sel)
    if family in {"team_total", "prop"}:
        if result.stat is None or line is None:
            raise GradeError("GRADE_STAT_OR_LINE_MISSING")
        return _cmp(_real(result.stat, "STAT"), _real(line, "LINE"), sel)
    if family == "yes_no":
        if sel not in {"YES", "NO", "OVER", "UNDER"}:
            raise GradeError(f"GRADE_SELECTION_INVALID:{sel}")
        if line is not None:
            # A supplied threshold is evidence even when the final is boolean-only.
            # Do not silently grade malformed display lines from raw Mapping callers.
            _real(line, "LINE")
        if result.occurred is not None and not isinstance(result.occurred, bool):
            raise GradeError("GRADE_OCCURRED_INVALID")
        if result.stat is not None and line is None:
            # A numeric final cannot be reconciled without its threshold.
            # Do not silently select the boolean while ignoring that stat.
            raise GradeError("GRADE_PARTIAL_NUMERIC_EVIDENCE")
        if line is not None and result.stat is not None:
            value = _real(result.stat, "STAT")
            threshold = _real(line, "LINE")
            numeric_event = _cmp(value, threshold, "OVER")
            if result.occurred is not None:
                # Both fields describe the same occurrence. A numeric push
                # cannot be represented by a boolean, and conflicting
                # evidence must never produce a settled grade.
                if numeric_event == PUSH or result.occurred != (numeric_event == WIN):
                    raise GradeError("GRADE_EVIDENCE_CONFLICT")
            direction = "OVER" if sel in {"YES", "OVER"} else "UNDER"
            return _cmp(value, threshold, direction)
        if result.occurred is None:
            raise GradeError("GRADE_OCCURRED_MISSING")
        # Boolean-only final evidence is valid with or without a listed
        # display line (e.g. anytime-TD YES 0.5 with no numeric stat).
        return WIN if result.occurred == (sel in {"YES", "OVER"}) else LOSS
    raise GradeError(f"GRADE_FAMILY_UNKNOWN:{family}")


def units(outcome: str, dk_price: int, stake: float = 1.0) -> float:
    if outcome not in (WIN, LOSS, PUSH):
        raise GradeError(f"GRADE_OUTCOME_INVALID:{outcome}")
    stake = _real(stake, "STAKE", nonnegative=True)
    decimal = _finite_derived(american_to_decimal(dk_price), "PAYOUT")
    if outcome == WIN:
        return _finite_derived(stake * (decimal - 1), "PAYOUT")
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
    if entry_line is not None:
        entry_line = _real(entry_line, "ENTRY_LINE")
    if close_line is not None:
        close_line = _real(close_line, "CLOSE_LINE")
    if (entry_line is None) != (close_line is None) or (
            entry_line is not None and abs(entry_line - close_line) > _EPS):
        raise GradeError(f"CLV_LINE_MOVED:{entry_line}->{close_line}")
    return no_vig_probability(close_price, close_opposite) - no_vig_probability(entry_price, entry_opposite)
