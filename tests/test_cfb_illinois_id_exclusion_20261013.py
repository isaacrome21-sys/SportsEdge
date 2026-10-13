"""ID-keyed Illinois exclusion for CFB (owner rule: no Illinois college
teams on user-facing cards), Oct 13, 2026.

The pre-fix mechanism was a normalized-name list (free_models
IL_COLLEGE_NAMES). It caught 7 of the 8 Illinois schools fielding 2026
CFB teams but MISSED Chicago State (ESPN id 2130) in every attested name
form -- a live miss (11-game FCS schedule). These tests prove the
ID-keyed enforcement on the verified ESPN directory binding:

  * the prepricing stage excludes a fixture when EITHER competitor's
    resolved ESPN id is in the frozen registry
    (free_models.IL_COLLEGE_ESPN_IDS), whatever name form the row
    carried;
  * team/total derivative pricing (team_half_pricing) raises on a
    resolved registry id even for a name form the name list never
    contained ("CHST");
  * an Illinois team whose id cannot be resolved still fails closed at
    intake (BLOCK_TEAMS_UNRESOLVED) -- never silently priced;
  * non-Illinois fixtures (incl. the Northwestern State name trap) are
    unaffected;
  * the name list remains as the secondary signal for provider-less
    paths and now carries Chicago State's attested forms.

Directory entries below are transcribed from the live ESPN CFB teams
payload captured 2026-10-13 (cfb_participation_design samples):
(id, displayName, name, shortDisplayName, abbreviation, location).
"""
from datetime import datetime, timezone

import pytest

from artifacts import free_models
from sportsedge.prepricing import factor_ingestion as fi
from sportsedge import team_half_pricing as team_half

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-17T17:00:00Z"
ESPN = "https://site.api.espn.com/apis/site/v2/sports"
CFB_TEAMS_URL = f"{ESPN}/football/college-football/teams?limit=500"

TEAM_FIELDS = {
    "356": ("Illinois Fighting Illini", "Fighting Illini", "Illinois",
            "ILL", "Illinois"),
    "77": ("Northwestern Wildcats", "Wildcats", "Northwestern",
           "NU", "Northwestern"),
    "2287": ("Illinois State Redbirds", "Redbirds", "Illinois St",
             "ILST", "Illinois State"),
    "2459": ("Northern Illinois Huskies", "Huskies", "N Illinois",
             "NIU", "Northern Illinois"),
    "79": ("Southern Illinois Salukis", "Salukis", "S Illinois",
           "SIU", "Southern Illinois"),
    "2197": ("Eastern Illinois Panthers", "Panthers", "E Illinois",
             "EIU", "Eastern Illinois"),
    "2710": ("Western Illinois Leathernecks", "Leathernecks",
             "W Illinois", "WIU", "Western Illinois"),
    "2130": ("Chicago State Cougars", "Cougars", "Chicago St",
             "CHST", "Chicago State"),
    "48": ("Delaware Blue Hens", "Blue Hens", "Delaware",
           "DEL", "Delaware"),
    "2393": ("Middle Tennessee Blue Raiders", "Blue Raiders",
             "Middle Tenn", "MTSU", "Middle Tennessee"),
    "2466": ("Northwestern State Demons", "Demons", "N'Western St",
             "NWST", "Northwestern State"),
}

# The 8 Illinois schools fielding CFB teams in 2026.
FOOTBALL_SCHOOLS = ["356", "77", "2287", "2459", "79", "2197", "2710",
                    "2130"]


class FakeGetter:
    """Recorded-fixture getter: unmapped URLs fail like a dead network."""

    def __init__(self, mapping):
        self.mapping = dict(mapping)
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url not in self.mapping:
            raise OSError("UNMAPPED_URL:" + url)
        return self.mapping[url]


def _team_dict(tid):
    dn, nm, short, abbr, loc = TEAM_FIELDS[tid]
    return {"id": tid, "displayName": dn, "name": nm,
            "shortDisplayName": short, "abbreviation": abbr,
            "location": loc}


def _directory(ids):
    return {"sports": [{"leagues": [{"teams": [
        {"team": _team_dict(t)} for t in ids]}]}]}


def _scoreboard(home_id, away_id):
    def comp(tid, home_away):
        return {"homeAway": home_away, "team": _team_dict(tid)}
    return {"events": [{"id": "401999001", "date": KICKOFF,
                        "competitions": [{
                            "competitors": [comp(home_id, "home"),
                                            comp(away_id, "away")],
                            "venue": {"indoor": False,
                                      "fullName": "Test Stadium",
                                      "address": {"city": "Chicago",
                                                  "state": "IL"}}}]}]}


def _mapping(home_id, away_id, directory_ids=None):
    ids = directory_ids if directory_ids is not None else [home_id,
                                                           away_id]
    return {
        CFB_TEAMS_URL: _directory(ids),
        f"{ESPN}/football/college-football/scoreboard?dates=20261016"
        "&limit=500": {"events": []},
        f"{ESPN}/football/college-football/scoreboard?dates=20261017"
        "&limit=500": _scoreboard(home_id, away_id),
        f"{ESPN}/football/college-football/scoreboard?dates=20261018"
        "&limit=500": {"events": []},
    }


def _row(home_name, away_name):
    return {"sport": "CFB", "market": "SPREAD", "away": away_name,
            "home": home_name, "side": "HOME", "line": -3.5,
            "odds": -110, "commence_time": KICKOFF}


def _stage(row, mapping, **kw):
    return fi.stage_games([row], now=NOW, getter=FakeGetter(mapping),
                          **kw)[0]


# ---------------------------------------------------------------- registry

def test_registry_is_the_frozen_13_school_record():
    assert free_models.IL_COLLEGE_ESPN_IDS == {
        "356": "Illinois", "77": "Northwestern", "305": "DePaul",
        "2350": "Loyola Chicago", "82": "UIC", "71": "Bradley",
        "2287": "Illinois State", "79": "Southern Illinois",
        "2565": "SIU Edwardsville", "2197": "Eastern Illinois",
        "2710": "Western Illinois", "2459": "Northern Illinois",
        "2130": "Chicago State",
    }
    for tid in FOOTBALL_SCHOOLS:
        assert tid in free_models.IL_COLLEGE_ESPN_IDS


# ---------------------------------------------------------------- stage

@pytest.mark.parametrize("tid", FOOTBALL_SCHOOLS)
def test_stage_excludes_each_football_school_by_id(tid):
    stage = _stage(_row(TEAM_FIELDS[tid][0], TEAM_FIELDS["48"][0]),
                   _mapping(tid, "48"))
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_IL_COLLEGE_EXCLUDED
    assert f"IL_COLLEGE_ESPN_ID_{tid}" in stage["block_detail"]
    assert "(HOME)" in stage["block_detail"]


@pytest.mark.parametrize("form", ["Chicago State",
                                  "Chicago State Cougars",
                                  "Chicago St", "CHST"])
def test_stage_excludes_chicago_state_in_every_name_form(form):
    # None of these forms was in the pre-fix name list; the exclusion
    # can only come from the resolved ESPN id (2130).
    stage = _stage(_row(form, TEAM_FIELDS["48"][0]),
                   _mapping("2130", "48"))
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_IL_COLLEGE_EXCLUDED
    assert "IL_COLLEGE_ESPN_ID_2130" in stage["block_detail"]


def test_stage_excludes_illinois_team_on_the_away_side():
    stage = _stage(_row(TEAM_FIELDS["48"][0], "Chicago State"),
                   _mapping("48", "2130"))
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_IL_COLLEGE_EXCLUDED
    assert "(AWAY)" in stage["block_detail"]


def test_stage_unresolved_illinois_identity_fails_closed():
    # The directory lacks id 2130: the team cannot be bound, so the
    # fixture blocks as teams-unresolved -- never silently priced, and
    # never waved through the Illinois filter.
    mapping = _mapping("2130", "48", directory_ids=["48"])
    stage = _stage(_row("Chicago State", TEAM_FIELDS["48"][0]), mapping)
    assert stage["blocked"] is True
    assert stage["block_reason"] == fi.BLOCK_TEAMS_UNRESOLVED


def test_stage_non_illinois_fixture_is_not_il_blocked():
    stage = _stage(_row(TEAM_FIELDS["2393"][0], TEAM_FIELDS["48"][0]),
                   _mapping("2393", "48"))
    assert stage["block_reason"] != fi.BLOCK_IL_COLLEGE_EXCLUDED
    assert "IL_COLLEGE" not in stage["block_detail"]
    # It flows on to the next gate (QB identity on the sparse feed).
    assert stage["block_reason"] == fi.BLOCK_QB_IDENTITY_UNVERIFIED


def test_stage_northwestern_state_is_not_the_illinois_northwestern():
    stage = _stage(_row(TEAM_FIELDS["2466"][0], TEAM_FIELDS["48"][0]),
                   _mapping("2466", "48"))
    assert stage["block_reason"] != fi.BLOCK_IL_COLLEGE_EXCLUDED
    assert "IL_COLLEGE" not in stage["block_detail"]


def test_stage_manual_mode_audits_but_does_not_block():
    stage = _stage(_row("Chicago State", TEAM_FIELDS["48"][0]),
                   _mapping("2130", "48"), enforce_blocks=False)
    assert stage["blocked"] is False
    assert stage["block_reason"] == ""
    assert "IL_COLLEGE_ESPN_ID_2130" in stage["block_detail"]


# ---------------------------------------------------------------- team_half

def _directory_getter(ids):
    def getter(url):
        if url == CFB_TEAMS_URL:
            return _directory(ids)
        return None
    return getter


def _team_half_row(home, away):
    return {"sport": "CFB", "away": away, "home": home,
            "kickoff": KICKOFF, "team": "HOME", "side": "OVER",
            "market": "TEAM_TOTAL", "line": 22.5, "odds": -110,
            "book": "draftkings",
            "quote_captured_at": "2026-10-13T17:59:00Z"}


def test_team_half_excludes_chicago_state_by_id_not_name():
    # "CHST" is an abbreviation form the name list never contained; the
    # raise can only come from the resolved ESPN id.
    out = team_half.price_team_half_rows(
        [_team_half_row("CHST", "Delaware Blue Hens")], now=NOW,
        getter=_directory_getter(["2130", "48"]))[0]
    assert "ILLINOIS_COLLEGE_EXCLUDED" in out[0]["reason"]


def test_team_half_northwestern_state_passes_the_il_filter():
    out = team_half.price_team_half_rows(
        [_team_half_row("NWST", "Delaware Blue Hens")], now=NOW,
        getter=_directory_getter(["2466", "48"]))[0]
    assert "ILLINOIS_COLLEGE_EXCLUDED" not in out[0]["reason"]
    # It proceeds to fixture verification, which fails closed on the
    # absent scoreboard -- the IL filter is not what stops it.
    assert "UNIQUE_PUBLIC_MATCHUP_REQUIRED" in out[0]["reason"]


# ---------------------------------------------------------------- calculate
# Secondary signal: the name list serves provider-less paths and now
# carries Chicago State's attested forms.

@pytest.mark.parametrize("form", ["Chicago State",
                                  "Chicago State Cougars", "Chicago St"])
def test_calculate_name_list_now_covers_chicago_state(form):
    result = free_models.calculate(
        {"sport": "CFB", "away": form, "home": "Purdue Boilermakers",
         "market": "SPREAD", "side": "AWAY", "line": 3.5, "odds": -110,
         "kickoff": KICKOFF}, None, NOW, auto_context=False)
    assert result["status"] == "BLOCKED_IL_COLLEGE"
    assert result["reason"] == "IL_COLLEGE_EXCLUDED"


def test_calculate_northwestern_state_still_not_blocked():
    result = free_models.calculate(
        {"sport": "CFB", "away": "Northwestern State",
         "home": "Louisiana", "market": "SPREAD", "side": "AWAY",
         "line": 7.5, "odds": -110, "kickoff": KICKOFF}, None, NOW,
        auto_context=False)
    assert result["status"] != "BLOCKED_IL_COLLEGE"
