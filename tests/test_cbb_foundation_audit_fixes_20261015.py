"""Regression tests for the independent audit findings on #2350 (CBB foundation)."""
import random

import pytest

from sportsedge.research import cbb_foundation as F
from sportsedge.research.cbb_foundation import Event, FoundationError, GamePath, PlayerInput, TeamInput

S = F.SPORT


def _team(tid, espn_id, **kw):
    return TeamInput(tid, tuple(PlayerInput(f"{tid}_p{i}", 8, 2.5, 4) for i in range(5)),
                     espn_id=espn_id, **kw)


# Non-Illinois synthetic ESPN ids (not in IL_COLLEGE_ESPN_IDS).
H, A = _team("HOM", "90001"), _team("AWY", "90002")

FAIL_OPEN = ["DePaul Blue Demons", "Bradley Braves", "SIUE", "SIUE Cougars",
             "Loyola (IL) Ramblers", "ILL", "Loyola Ramblers", "Illinois-Chicago Flames",
             "Southern Illinois Univ", "Chicago St. Cougars", "Northwestern Wildcats"]


@pytest.mark.parametrize("name", FAIL_OPEN)
def test_illinois_aliases_blocked(name):
    assert F.illinois_excluded(name)
    r = F.market_terminal("MONEYLINE", name, "AWY")
    assert r["terminal"] == "BLOCKED_BY_AUTHORIZATION"
    with pytest.raises(FoundationError) as e:
        F.simulate_game(_team(name, "90001"), A, random.Random(1))
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"


@pytest.mark.parametrize("name", ["Northwestern State", "Indiana State", "Indiana",
                                  "Loyola Marymount", "Loyola Maryland", "Iowa"])
def test_lookalikes_still_allowed(name):
    assert not F.illinois_excluded(name)


@pytest.mark.parametrize("espn_id", [None, "", "  "])
def test_missing_espn_id_fails_closed(espn_id):
    with pytest.raises(FoundationError) as e:
        F.simulate_game(_team("HOM", espn_id), A, random.Random(1))
    assert e.value.code == "CBB_ESPN_ID_MISSING"


def test_settle_checks_display_name_and_espn_id():
    p = F.simulate_game(H, A, random.Random(2))
    with pytest.raises(FoundationError) as e:
        F.settle(p, "TOTAL", line=0.5, home=_team("HOM", "90001", display_name="DePaul"), away=A)
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
    with pytest.raises(FoundationError) as e:
        F.settle(p, "TOTAL", line=0.5, home=_team("HOM", "305"), away=A)
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
    with pytest.raises(FoundationError) as e:
        F.settle(p, "TOTAL", line=0.5, home=_team("HOM", None), away=A)
    assert e.value.code == "CBB_ESPN_ID_MISSING"
    assert F.settle(p, "TOTAL", line=0.5) in ("OVER", "UNDER")


@pytest.mark.parametrize("events", [[], [Event("HOM", "HOM_p0", 1, "FG2"),
                                         Event("AWY", "AWY_p0", 2, "FG2")]])
def test_empty_or_tied_path_refused(events):
    p = GamePath("HOM", "AWY", list(events), teams=(H, A))
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MONEYLINE", selection="HOM")
    assert e.value.code == f"{S}_GAME_ENDED_TIED"


def test_settle_runs_check_path_and_requires_rosters():
    p = GamePath("HOM", "AWY", [Event("HOM", "AWY_p0", 1, "FG2")], teams=(H, A))
    with pytest.raises(FoundationError) as e:
        F.settle(p, "MONEYLINE", selection="HOM")
    assert e.value.code == f"{S}_PLAYER_NOT_ON_TEAM"
    with pytest.raises(FoundationError) as e:
        F.settle(GamePath("HOM", "AWY", [Event("HOM", "HOM_p0", 1, "FG2")]), "TOTAL", line=0.5)
    assert e.value.code == f"{S}_PATH_ROSTERS_MISSING"


def test_ghost_player_refused_unless_rostered():
    p = F.simulate_game(H, A, random.Random(4))
    with pytest.raises(FoundationError) as e:
        F.settle(p, "PLAYER_POINTS", player_id="GHOST", team_id="HOM", line=0.5)
    assert e.value.code == f"{S}_PLAYER_IDENTITY_MISMATCH"
    assert F.settle(p, "PLAYER_POINTS", player_id="HOM_p0", team_id="HOM", line=0.5) in ("OVER", "UNDER")


@pytest.mark.parametrize("name", ["DePaul Blue Demons", "Bradley Braves", "SIUE",
                                  "Loyola (IL) Ramblers"])
def test_owner_demonstrated_bypass_refused_without_espn_id(name):
    """#2350 owner hold: these names were admitted with ESPN id omitted."""
    with pytest.raises(FoundationError) as e:
        TeamInput(name, H.players).validate()
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"


@pytest.mark.parametrize("espn_id", ["305", " 305 ", "0305", 305, "305.0"])
def test_variant_illinois_ids_and_name_conflict_refused(espn_id):
    with pytest.raises(FoundationError) as e:
        TeamInput("Gonzaga Bulldogs", H.players, espn_id=espn_id).validate()
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
