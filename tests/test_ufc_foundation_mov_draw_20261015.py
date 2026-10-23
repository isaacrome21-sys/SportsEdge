"""#2351 owner ruling (2026-10-15 21:46Z): fighter-specific Method of Victory LOSES on
DRAW (scorecard draw and technical draw); an offered DRAW selection WINS; NC VOID."""
import pytest

from sportsedge.research import ufc_foundation as F
from sportsedge.research.ufc_foundation import BoutPath, FoundationError

DRAW = BoutPath("RED", "BLU", 3, "DRAW", None, 3, 300)
TECH = BoutPath("RED", "BLU", 3, "TECHNICAL_DRAW", None, 2, 200)
NC = BoutPath("RED", "BLU", 3, "NO_CONTEST", None, 2, 30)
HOWS = ("KO_TKO_DQ", "SUBMISSION", "DECISION")


@pytest.mark.parametrize("b", [DRAW, TECH])
@pytest.mark.parametrize("fid", ["RED", "BLU"])
@pytest.mark.parametrize("how", HOWS)
def test_fighter_method_loses_on_draw(b, fid, how):
    assert F.settle(b, "METHOD_OF_VICTORY", selection=(fid, how)) == "LOSE"
    assert F.settle(b, "METHOD_OF_VICTORY", selection=(fid, how), draw_offered=True) == "LOSE"


@pytest.mark.parametrize("b", [DRAW, TECH])
def test_offered_draw_selection_wins_on_draw(b):
    assert F.settle(b, "METHOD_OF_VICTORY", selection="DRAW", draw_offered=True) == "WIN"


def test_offered_draw_selection_loses_on_completed_fight_and_true_win_settles():
    b = BoutPath("RED", "BLU", 3, "SUBMISSION", "BLU", 2, 100)
    assert F.settle(b, "METHOD_OF_VICTORY", selection="DRAW", draw_offered=True) == "LOSE"
    res = {(f, h): F.settle(b, "METHOD_OF_VICTORY", selection=(f, h))
           for f in ("RED", "BLU") for h in HOWS}
    assert [k for k, v in res.items() if v == "WIN"] == [("BLU", "SUBMISSION")]


@pytest.mark.parametrize("kw", [{}, {"draw_offered": False}, {"draw_offered": "yes"}])
def test_unoffered_draw_selection_refused(kw):
    for b in (DRAW, NC, BoutPath("RED", "BLU", 3, "KO_TKO", "RED", 1, 10)):
        with pytest.raises(FoundationError) as e:
            F.settle(b, "METHOD_OF_VICTORY", selection="DRAW", **kw)
        assert e.value.code == "UFC_SELECTION_IDENTITY_MISMATCH"


def test_no_contest_still_void_after_validation():
    assert F.settle(NC, "METHOD_OF_VICTORY", selection=("RED", "DECISION")) == "VOID"
    assert F.settle(NC, "METHOD_OF_VICTORY", selection="DRAW", draw_offered=True) == "VOID"
    with pytest.raises(FoundationError):
        F.settle(NC, "METHOD_OF_VICTORY", selection=("GRN", "DECISION"))


def test_technical_draw_other_markets():
    assert F.check_bout(TECH)
    assert F.settle(TECH, "MONEYLINE", selection="RED") == "PUSH"
    assert F.settle(TECH, "GOES_THE_DISTANCE", selection="NO") == "WIN"
    assert F.settle(TECH, "TOTAL_ROUNDS", line=1.5) == "OVER"
    assert F.settle(TECH, "FIGHTER_TO_WIN_IN_ROUND", selection="RED", round_no=2) == "LOSE"
    assert F.settle(TECH, "WIN_AND_TOTAL_ROUNDS", selection=("RED", "OVER"), line=1.5) == "LOSE"
    with pytest.raises(FoundationError):
        F.check_bout(BoutPath("RED", "BLU", 3, "TECHNICAL_DRAW", "RED", 2, 140))
