"""#2350 re-audit (hard authorization): every Illinois D1 school by every reasonable
form is refused; espn_id is validated against a registry (unknown ids fail closed);
the props layer enforces its own Illinois check."""
import random

import pytest

from sportsedge.research import cbb_foundation as F
from sportsedge.research import cbb_foundation_props as P
from sportsedge.research.cbb_foundation import (Event, FoundationError, GamePath, PlayerInput,
                                                TeamInput)

FORMS = {
    "Illinois": ["Illinois", "Illinois Fighting Illini", "Fighting Illini", "Illini",
                 "University of Illinois", "Univ. of Illinois", "U of I", "UIUC", "ILL",
                 "Illinois Urbana-Champaign", "Ill."],
    "Northwestern": ["Northwestern", "Northwestern Wildcats", "Northwestern University",
                     "NWU", "Northwestern (Ill.)"],
    "DePaul": ["DePaul", "DePaul Blue Demons", "DePaul University", "DEP", "Blue Demons"],
    "Loyola Chicago": ["Loyola Chicago", "Loyola-Chicago Ramblers", "Loyola (Ill.)",
                       "Loyola (IL)", "Loyola (IL) Ramblers", "Loyola University Chicago",
                       "LUC", "Loyola Ramblers"],
    "UIC": ["UIC", "UIC Flames", "Illinois-Chicago", "Illinois Chicago Flames",
            "University of Illinois Chicago"],
    "Bradley": ["Bradley", "Bradley Braves", "Bradley University", "BRAD"],
    "Illinois State": ["Illinois State", "Illinois State Redbirds", "Illinois St.",
                       "ILST", "Illinois State University", "Redbirds"],
    "Southern Illinois": ["Southern Illinois", "Southern Illinois Salukis", "SIU",
                          "Southern Ill.", "Salukis", "Southern Illinois University"],
    "SIUE": ["SIU Edwardsville", "SIUE", "SIUE Cougars", "SIU-Edwardsville Cougars",
             "Southern Illinois University Edwardsville"],
    "Eastern Illinois": ["Eastern Illinois", "Eastern Illinois Panthers", "EIU",
                         "EIU Panthers", "Eastern Ill.", "Eastern Illinois University"],
    "Western Illinois": ["Western Illinois", "Western Illinois Leathernecks", "WIU",
                         "Leathernecks", "Western Ill.", "Western Illinois University"],
    "Northern Illinois": ["Northern Illinois", "Northern Illinois Huskies", "NIU",
                          "NIU Huskies", "Northern Ill.", "Northern Illinois University"],
    "Chicago State": ["Chicago State", "Chicago State Cougars", "Chicago St.", "CHST",
                      "Chicago State University"],
}
ALL = [(s, n) for s, ns in FORMS.items() for n in ns]


def _team(tid, espn_id, **kw):
    return TeamInput(tid, tuple(PlayerInput(f"{tid}_p{i}", 8, 2.5, 4) for i in range(5)),
                     espn_id=espn_id, **kw)


@pytest.mark.parametrize("school,name", ALL)
def test_every_illinois_form_refused(school, name):
    assert F.illinois_excluded(name), (school, name)
    assert F.market_terminal("MONEYLINE", name, "AWY")["terminal"] == "BLOCKED_BY_AUTHORIZATION"
    with pytest.raises(FoundationError) as e:
        _team(name, None).validate()
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
    with pytest.raises(FoundationError) as e:
        _team("HOM", "SYN-0001", display_name=name).validate()
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"


@pytest.mark.parametrize("name", ["Indiana", "Indiana State", "Northwestern State",
                                  "Loyola Marymount", "Loyola Maryland", "Iowa", "Iowa State",
                                  "Eastern Michigan", "Western Michigan", "Northern Iowa",
                                  "Southern Indiana", "Boston University", "Florida Panthers"])
def test_non_illinois_not_overblocked(name):
    assert not F.illinois_excluded(name)


@pytest.mark.parametrize("espn_id", ["99999", "90001", "12345", "abc", "SYN-9999"])
def test_unknown_espn_id_fails_closed(espn_id):
    with pytest.raises(FoundationError) as e:
        _team("HOM", espn_id).validate()
    assert e.value.code == "CBB_ESPN_ID_UNREGISTERED"


def test_registered_synthetic_id_bound_to_team_id():
    _team("HOM", "SYN-0001").validate()
    with pytest.raises(FoundationError) as e:
        _team("AWY", "SYN-0001").validate()          # id/name conflict
    assert e.value.code == "CBB_ESPN_ID_NAME_CONFLICT"


def test_every_illinois_registry_id_refused():
    from artifacts.free_models import IL_COLLEGE_ESPN_IDS
    for i in IL_COLLEGE_ESPN_IDS:
        with pytest.raises(FoundationError) as e:
            _team("HOM", i).validate()
        assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"


def test_props_layer_independent_illinois_check():
    H, A = _team("HOM", "SYN-0001"), _team("AWY", "SYN-0002")
    g = F.simulate_game(H, A, random.Random(1))
    pp = {x: P.PlayerPropsInput() for x in H.roster}
    ap = P.TeamPropsInput("AWY", {x: P.PlayerPropsInput() for x in A.roster})
    props = P.simulate_props(g, H, A, P.TeamPropsInput("HOM", pp), ap, random.Random(2))
    # tampered props path: an Illinois team identity injected after the game layer
    props.rosters = {"DePaul Blue Demons": props.rosters["HOM"], "AWY": props.rosters["AWY"]}
    with pytest.raises(FoundationError) as e:
        P.settle_prop(props, "RACE_TO_POINTS", selection="AWY", n=10)
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
    assert P.illinois_guard("Bradley University") is True
    # a game path whose bound team carries an Illinois display name
    bad = _team("HOM", "SYN-0001")
    object.__setattr__(bad, "display_name", "EIU Panthers")
    with pytest.raises(FoundationError) as e:
        P.simulate_props(g, bad, A, P.TeamPropsInput("HOM", pp), ap, random.Random(2))
    assert e.value.code == "ILLINOIS_COLLEGE_EXCLUDED"
