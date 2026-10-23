"""Regression tests for #2351 audit findings + owner DK settlement rulings (2026-10-15)."""
import pytest

from sportsedge.research import ufc_foundation as F
from sportsedge.research.ufc_foundation import BoutPath, FoundationError

D = BoutPath("RED", "BLU", 3, "DRAW", None, 3, 300)
NC = BoutPath("RED", "BLU", 5, "NO_CONTEST", None, 2, 30)


def test_two_way_moneyline_draw_pushes():
    assert F.settle(D, "MONEYLINE", selection="RED") == "PUSH"
    assert F.settle(D, "MONEYLINE", selection="BLU") == "PUSH"


@pytest.mark.parametrize("r", [1, 2, 3])
def test_fighter_to_win_in_round_loses_on_draw(r):
    assert F.settle(D, "FIGHTER_TO_WIN_IN_ROUND", selection="RED", round_no=r) == "LOSE"


def test_fighter_to_win_in_round_basic():
    b = BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 2, 100)
    assert F.settle(b, "FIGHTER_TO_WIN_IN_ROUND", selection="RED", round_no=2) == "WIN"
    assert F.settle(b, "FIGHTER_TO_WIN_IN_ROUND", selection="RED", round_no=1) == "LOSE"
    assert F.settle(b, "FIGHTER_TO_WIN_IN_ROUND", selection="BLU", round_no=2) == "LOSE"


@pytest.mark.parametrize("ou", ["OVER", "UNDER"])
def test_win_and_total_rounds_combo_loses_on_draw(ou):
    assert F.settle(D, "WIN_AND_TOTAL_ROUNDS", selection=("RED", ou), line=1.5) == "LOSE"


def test_win_and_total_rounds_combo_basic():
    b = BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 3, 200)
    assert F.settle(b, "WIN_AND_TOTAL_ROUNDS", selection=("RED", "OVER"), line=2.5) == "WIN"
    assert F.settle(b, "WIN_AND_TOTAL_ROUNDS", selection=("RED", "UNDER"), line=2.5) == "LOSE"
    assert F.settle(b, "WIN_AND_TOTAL_ROUNDS", selection=("BLU", "OVER"), line=2.5) == "LOSE"
    with pytest.raises(FoundationError):
        F.settle(b, "WIN_AND_TOTAL_ROUNDS", selection=("RED", "MAYBE"), line=2.5)


def test_total_rounds_settles_elapsed_time_on_draw():
    assert F.settle(D, "TOTAL_ROUNDS", line=2.5) == "OVER"
    assert F.settle(D, "TOTAL_ROUNDS", line=1.5) == "OVER"


def test_generic_round_betting_refused():
    with pytest.raises(FoundationError) as e:
        F.settle(BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 1, 10), "ROUND_BETTING",
                 selection="RED", round_no=1)
    assert e.value.code == "UFC_MARKET_AMBIGUOUS"
    assert F.market_terminal("ROUND_BETTING")["terminal"] == "NO_SETTLEMENT"


@pytest.mark.parametrize("mkt,kw", [
    ("MONEYLINE", {"selection": "GRN"}),
    ("METHOD_OF_VICTORY", {"selection": ("RED", "KO")}),
    ("FIGHTER_TO_WIN_IN_ROUND", {"selection": "RED", "round_no": 9}),
    ("FIGHTER_TO_WIN_IN_ROUND", {"selection": "GRN", "round_no": 1}),
    ("GOES_THE_DISTANCE", {"selection": "RED"}),
    ("TOTAL_ROUNDS", {"line": float("nan")}),
    ("TOTAL_ROUNDS", {"line": float("inf")}),
    ("TOTAL_ROUNDS", {"line": None}),
    ("TOTAL_ROUNDS", {"line": 7.5}),
    ("WIN_AND_TOTAL_ROUNDS", {"selection": ("GRN", "OVER"), "line": 1.5}),
])
def test_no_contest_validates_identity_and_line_before_void(mkt, kw):
    with pytest.raises(FoundationError):
        F.settle(NC, mkt, **kw)


def test_no_contest_valid_request_voids():
    assert F.settle(NC, "MONEYLINE", selection="RED") == "VOID"
    assert F.settle(NC, "TOTAL_ROUNDS", line=1.5) == "VOID"
    assert F.settle(NC, "GOES_THE_DISTANCE", selection="NO") == "VOID"


@pytest.mark.parametrize("field,val", [("end_round", True), ("end_second", True),
                                       ("scheduled_rounds", True)])
def test_bool_is_not_an_int(field, val):
    kw = dict(red_id="RED", blue_id="BLU", scheduled_rounds=3, method="KO_TKO",
              winner="RED", end_round=1, end_second=10)
    kw[field] = val
    with pytest.raises(FoundationError):
        F.check_bout(BoutPath(**kw))
