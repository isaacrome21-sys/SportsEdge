"""#2351 re-audit: a NO_CONTEST must not VOID a market whose outcome was already
decided before the stoppage; undecided markets stay VOID."""
import pytest

from sportsedge.research import ufc_foundation as F
from sportsedge.research.ufc_foundation import BoutPath

NC_R3 = BoutPath("RED", "BLU", 3, "NO_CONTEST", None, 3, 40)    # elapsed 640s
NC_R1 = BoutPath("RED", "BLU", 3, "NO_CONTEST", None, 1, 40)


def test_over_already_decided_settles_over():
    assert F.settle(NC_R3, "TOTAL_ROUNDS", line=1.5) == "OVER"     # decided at R2 2:30
    assert F.settle(NC_R3, "TOTAL_ROUNDS", line=2.5) == "VOID"     # not yet decided


def test_round_already_passed_without_win_loses():
    for r in (1, 2):
        assert F.settle(NC_R3, "FIGHTER_TO_WIN_IN_ROUND", selection="RED", round_no=r) == "LOSE"
    assert F.settle(NC_R3, "FIGHTER_TO_WIN_IN_ROUND", selection="RED", round_no=3) == "VOID"


def test_combo_under_leg_already_lost():
    assert F.settle(NC_R3, "WIN_AND_TOTAL_ROUNDS", selection=("RED", "UNDER"), line=1.5) == "LOSE"
    assert F.settle(NC_R3, "WIN_AND_TOTAL_ROUNDS", selection=("RED", "OVER"), line=1.5) == "VOID"


def test_never_void_a_decided_market():
    for ln in (0.5, 1.5):
        assert F.settle(NC_R3, "TOTAL_ROUNDS", line=ln) != "VOID"


def test_undecided_markets_stay_void():
    assert F.settle(NC_R1, "TOTAL_ROUNDS", line=0.5) == "VOID"
    assert F.settle(NC_R1, "MONEYLINE", selection="RED") == "VOID"
    assert F.settle(NC_R1, "METHOD_OF_VICTORY", selection=("RED", "DECISION")) == "VOID"
    assert F.settle(NC_R1, "FIGHTER_TO_WIN_IN_ROUND", selection="BLU", round_no=1) == "VOID"
