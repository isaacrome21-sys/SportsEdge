"""Regression tests for the independent audit findings on #2348 (NHL foundation)."""
import random

import pytest

from sportsedge.research import nhl_foundation as nf
from sportsedge.research.nhl_foundation import Goal, GamePath, NHLFoundationError, TeamInput


def _team(tid):
    pl = [f"{tid}_p{i}" for i in range(4)]
    return TeamInput(tid, 3.0, {p: 0.25 for p in pl}, {p: 1.0 for p in pl}, 3.0)


H, A = _team("HOM"), _team("AWY")


def _sim():
    return nf.simulate_game(H, A, random.Random(5))


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), None, True, "1.5"])
def test_puck_line_line_validated_before_use(bad):
    p = _sim()
    with pytest.raises(NHLFoundationError) as e:
        nf.settle(p, "PUCK_LINE", selection="HOM", line=bad)
    assert e.value.code == "NHL_LINE_NONFINITE"


def test_settle_runs_check_path_misattributed_scorer():
    p = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "AWY_p0", ())])
    with pytest.raises(NHLFoundationError) as e:
        nf.settle(p, "MONEYLINE", selection="HOM", home=H, away=A)
    assert e.value.code == "NHL_SCORER_NOT_ON_TEAM"


def test_settle_refuses_tied_path_without_shootout():
    p = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "HOM_p0", ()),
                                Goal("AWY", 2, 1.0, "AWY_p0", ())])
    for mkt, sel in (("MONEYLINE", "AWY"), ("MONEYLINE", "HOM")):
        with pytest.raises(NHLFoundationError) as e:
            nf.settle(p, mkt, selection=sel, home=H, away=A)
        assert e.value.code == "NHL_GAME_ENDED_TIED"


def test_settle_refuses_path_without_rosters():
    p = GamePath("HOM", "AWY", [Goal("HOM", 1, 1.0, "AWY_p0", ())])
    with pytest.raises(NHLFoundationError) as e:
        nf.settle(p, "TOTAL", line=0.5)
    assert e.value.code == "NHL_PATH_ROSTERS_MISSING"


def test_simulated_path_carries_rosters_and_settles():
    assert nf.settle(_sim(), "TOTAL", line=0.5) in ("OVER", "UNDER")


@pytest.mark.parametrize("mkt", ["PLAYER_GOALS", "PLAYER_ASSISTS", "PLAYER_POINTS"])
def test_player_prop_unknown_player_refused(mkt):
    with pytest.raises(NHLFoundationError) as e:
        nf.settle(_sim(), mkt, player_id="GHOST_99", line=0.5)
    assert e.value.code == "NHL_PLAYER_IDENTITY_MISMATCH"
