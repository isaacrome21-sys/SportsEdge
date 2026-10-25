"""Conflicting or malformed binary final evidence must never settle a pick."""

from __future__ import annotations

import pytest

from sportsedge.pipeline.grading import FinalResult, GradeError, grade


@pytest.mark.parametrize("selection,stat,occurred", [
    ("YES", 1, False),
    ("NO", 0, True),
    ("OVER", 1, False),
    ("UNDER", 0, True),
    ("YES", 0.5, True),
    ("NO", 0.5, False),
])
def test_numeric_and_boolean_binary_finals_conflict(selection, stat, occurred):
    with pytest.raises(GradeError, match="GRADE_BINARY_FINAL_CONFLICT"):
        grade({"selection": selection, "line": 0.5},
              FinalResult(stat=stat, occurred=occurred), family="yes_no")


@pytest.mark.parametrize("selection,stat,occurred,expected", [
    ("YES", 1, True, "WIN"),
    ("NO", 0, False, "WIN"),
    ("YES", 0, False, "LOSS"),
    ("NO", 1, True, "LOSS"),
    ("OVER", 1, True, "WIN"),
    ("UNDER", 0, False, "WIN"),
])
def test_matching_dual_binary_finals_preserve_settlement(selection, stat, occurred, expected):
    assert grade({"selection": selection, "line": 0.5},
                 FinalResult(stat=stat, occurred=occurred), family="yes_no") == expected


@pytest.mark.parametrize("occurred", [0, 1, "True", [], {}])
def test_malformed_occurred_cannot_hide_behind_numeric_final(occurred):
    with pytest.raises(GradeError, match="GRADE_OCCURRED_INVALID"):
        grade({"selection": "YES", "line": 0.5},
              FinalResult(stat=1, occurred=occurred), family="yes_no")


def test_uncomparable_dual_final_without_line_refused():
    with pytest.raises(GradeError, match="GRADE_BINARY_FINAL_UNCOMPARABLE"):
        grade({"selection": "YES", "line": None},
              FinalResult(stat=1, occurred=True), family="yes_no")


@pytest.mark.parametrize("selection", [None, True, 1, [], {}, ""])
@pytest.mark.parametrize("family", ["yes_no", "moneyline"])
def test_nonstring_or_empty_selection_is_classified(selection, family):
    with pytest.raises(GradeError, match="GRADE_SELECTION_INVALID"):
        grade({"selection": selection, "line": 0.5},
              FinalResult(away_score=2, home_score=1, occurred=True),
              family=family)


def test_missing_selection_is_classified():
    with pytest.raises(GradeError, match="GRADE_SELECTION_INVALID"):
        grade({"line": 0.5}, FinalResult(occurred=True), family="yes_no")


def test_single_numeric_and_single_boolean_paths_unchanged():
    assert grade({"selection": "NO", "line": 0.5},
                 FinalResult(stat=0), family="yes_no") == "WIN"
    assert grade({"selection": "YES", "line": None},
                 FinalResult(occurred=True), family="yes_no") == "WIN"
