"""Never promote corrupted settlement/CLV or invert binary YES/NO outcomes."""

from __future__ import annotations

import math

import pytest

from sportsedge.pipeline.grading import (
    FinalResult,
    GradeError,
    grade,
    no_vig_clv,
    units,
)


@pytest.mark.parametrize("selection,stat,expected", [
    ("YES", 1, "WIN"),
    ("YES", 0, "LOSS"),
    ("NO", 0, "WIN"),
    ("NO", 1, "LOSS"),
    ("OVER", 1, "WIN"),
    ("UNDER", 0, "WIN"),
    ("YES", 0.5, "PUSH"),
    ("NO", 0.5, "PUSH"),
])
def test_numeric_binary_selections_settle_correctly(selection, stat, expected) -> None:
    assert grade({"selection": selection, "line": 0.5},
                 FinalResult(stat=stat), family="yes_no") == expected


@pytest.mark.parametrize("selection,occurred,expected", [
    ("YES", True, "WIN"), ("YES", False, "LOSS"),
    ("NO", True, "LOSS"), ("NO", False, "WIN"),
    ("OVER", True, "WIN"), ("UNDER", False, "WIN"),
])
def test_boolean_binary_selections_settle_correctly(selection, occurred, expected) -> None:
    assert grade({"selection": selection, "line": None},
                 FinalResult(occurred=occurred), family="yes_no") == expected


@pytest.mark.parametrize("family,pick,result", [
    ("moneyline", {"selection": "AWAY", "line": None}, FinalResult(math.nan, 3)),
    ("moneyline", {"selection": "AWAY", "line": None}, FinalResult(2, math.inf)),
    ("spread", {"selection": "AWAY", "line": 3.5}, FinalResult(-1, 3)),
    ("spread", {"selection": "HOME", "line": math.inf}, FinalResult(3, 7)),
    ("total", {"selection": "OVER", "line": 40.5}, FinalResult(30, math.nan)),
    ("total", {"selection": "UNDER", "line": -math.inf}, FinalResult(20, 20)),
    ("team_total", {"selection": "OVER", "line": 15.5}, FinalResult(stat=math.inf)),
    ("prop", {"selection": "UNDER", "line": math.nan}, FinalResult(stat=2)),
    ("prop", {"selection": "OVER", "line": 2.5}, FinalResult(stat=True)),
    ("yes_no", {"selection": "YES", "line": 0.5}, FinalResult(stat=math.nan)),
    ("yes_no", {"selection": "NO", "line": None}, FinalResult(occurred=1)),
])
def test_bad_finals_and_lines_refuse_grading(family, pick, result) -> None:
    with pytest.raises(GradeError, match="GRADE_.*INVALID"):
        grade(pick, result, family=family)


@pytest.mark.parametrize("family,selection,result", [
    ("total", "AWAY", FinalResult(3, 1)),
    ("prop", "YES", FinalResult(stat=2)),
    ("team_total", "HOME", FinalResult(stat=11)),
    ("yes_no", "AWAY", FinalResult(stat=1)),
    ("yes_no", "HOME", FinalResult(occurred=True)),
])
def test_wrong_selection_for_family_refused(family, selection, result) -> None:
    with pytest.raises(GradeError, match="GRADE_SELECTION_INVALID"):
        grade({"selection": selection, "line": 0.5}, result, family=family)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, True, "3.5"])
def test_clv_refuses_invalid_thresholds(bad) -> None:
    with pytest.raises(GradeError, match="GRADE_ENTRY_LINE_INVALID"):
        no_vig_clv(-110, -110, -115, +100, entry_line=bad, close_line=3.5)


@pytest.mark.parametrize("outcome", ["VOID", "", "DRAW", "PENDING", "win"])
def test_nonsettled_outcomes_cannot_be_recorded_as_zero_units(outcome) -> None:
    with pytest.raises(GradeError, match="GRADE_OUTCOME_INVALID"):
        units(outcome, -110)


@pytest.mark.parametrize("bad", [math.nan, math.inf, True, -0.2, "1"])
def test_units_refuse_bad_stakes(bad) -> None:
    with pytest.raises(GradeError, match="GRADE_STAKE_INVALID"):
        units("WIN", -110, stake=bad)


def test_correct_paired_no_vig_and_moneyline_units_unchanged() -> None:
    assert no_vig_clv(-110, -110, -115, -105, entry_line=3.5, close_line=3.5) > 0
    assert units("WIN", +150) == pytest.approx(1.5)
    assert units("LOSS", -110) == -1
    assert units("PUSH", -110) == 0
