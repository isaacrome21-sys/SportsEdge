"""Ladder evidence must fail closed on non-finite or non-numeric rows (#2670 HOLD)."""
from __future__ import annotations

import pytest

from sportsedge.pipeline import ladder

NAN, INF = float("nan"), float("inf")
GOOD_CLV = [0.01] * ladder.MIN_GRADED
GOOD_UNITS = [0.1] * ladder.MIN_GRADED
BAD_ROWS = [NAN, INF, -INF, "0.1", True, None]


def test_clean_evidence_reports_first_rung_only():
    assert ladder.evidence_supports(GOOD_CLV, units=GOOD_UNITS) == ladder.STAKE_025


@pytest.mark.parametrize("bad", BAD_ROWS, ids=repr)
def test_one_bad_clv_row_stays_paper(bad):
    clv = [bad] + GOOD_CLV[1:]
    assert ladder.evidence_supports(clv, units=GOOD_UNITS) == ladder.PAPER


@pytest.mark.parametrize("bad", BAD_ROWS, ids=repr)
def test_one_bad_units_row_stays_paper(bad):
    units = [bad] + GOOD_UNITS[1:]
    assert ladder.evidence_supports(GOOD_CLV, units=units) == ladder.PAPER


def test_overflowing_totals_stay_paper():
    huge = [1e308] * ladder.MIN_GRADED
    assert ladder.evidence_supports(GOOD_CLV, units=huge) == ladder.PAPER


def test_gate_edges_stay_paper():
    n = ladder.MIN_GRADED
    assert ladder.evidence_supports(GOOD_CLV) == ladder.PAPER
    assert ladder.evidence_supports(GOOD_CLV[:-1], units=GOOD_UNITS[:-1]) == ladder.PAPER
    assert ladder.evidence_supports(GOOD_CLV, units=GOOD_UNITS[:-1]) == ladder.PAPER
    assert ladder.evidence_supports([0.0] * n, units=GOOD_UNITS) == ladder.PAPER
    assert ladder.evidence_supports(GOOD_CLV, units=[0.0] * n) == ladder.PAPER


def test_owner_gate_is_fifty():
    assert ladder.MIN_GRADED == 50
    assert ladder.evidence_supports([0.01] * 49, units=[0.1] * 49) == ladder.PAPER
    assert ladder.evidence_supports([0.01] * 50, units=[0.1] * 50) == ladder.STAKE_025
