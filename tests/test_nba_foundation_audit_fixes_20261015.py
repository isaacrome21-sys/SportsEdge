"""Regression tests for the independent audit findings on #2349 (NBA foundation)."""
import random

import pytest

from sportsedge.research import nba_foundation as F
from sportsedge.research.nba_foundation import Event, FoundationError, GamePath, PlayerInput, TeamInput

S = F.SPORT


def _team(tid):
    return TeamInput(tid, tuple(PlayerInput(f"{tid}_p{i}", 8, 2.5, 4) for i in range(5)))


H, A = _team("HOM"), _team("AWY")


def _sim():
    return F.simulate_game(H, A, random.Random(3))


@pytest.mark.parametrize("events", [[], [Event("HOM", "HOM_p0", 1, "FG2"),
                                         Event("AWY", "AWY_p0", 2, "FG2")]])
@pytest.mark.parametrize("mkt,kw", [("MONEYLINE", {"selection": "HOM"}),
                                    ("TOTAL", {"line": 0.5}),
                                    ("SPREAD", {"selection": "AWY", "line": 1.5})])
def test_empty_or_tied_path_refused(events, mkt, kw):
    p = GamePath("HOM", "AWY", list(events), teams=(H, A))
    with pytest.raises(FoundationError) as e:
        F.settle(p, mkt, **kw)
    assert e.value.code == f"{S}_GAME_ENDED_TIED"


def test_settle_runs_check_path_misattributed_player():
    p = GamePath("HOM", "AWY", [Event("HOM", "AWY_p0", 1, "FG2")], teams=(H, A))
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MONEYLINE", selection="HOM")
    assert e.value.code == f"{S}_PLAYER_NOT_ON_TEAM"


def test_settle_refuses_path_without_rosters():
    p = GamePath("HOM", "AWY", [Event("HOM", "HOM_p0", 1, "FG2")])
    with pytest.raises(FoundationError) as e:
        F.settle(p, "TOTAL", line=0.5)
    assert e.value.code == f"{S}_PATH_ROSTERS_MISSING"


@pytest.mark.parametrize("mkt", ["PLAYER_POINTS", "PLAYER_THREES"])
def test_ghost_player_refused_unless_rostered(mkt):
    p = _sim()
    with pytest.raises(FoundationError) as e:
        F.settle(p, mkt, player_id="GHOST_1", team_id="HOM", line=0.5)
    assert e.value.code == f"{S}_PLAYER_IDENTITY_MISMATCH"
    assert F.settle(p, mkt, player_id="HOM_p0", team_id="HOM", line=0.5) in ("OVER", "UNDER")
