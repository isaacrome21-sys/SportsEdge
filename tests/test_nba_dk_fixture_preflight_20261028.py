"""Adversarial DK NBA roster preflight (all synthetic fixtures; no live odds)."""
import copy

import pytest

from sportsedge.sports.nba.espn_verified_source import (
    NBASource, NBADataError, NBA_ROSTER_URL,
)
from sportsedge.nba_dk_fixture_preflight import (
    SCREEN_STATUS, screen_nba_dk_player_rows,
)

TIP = "2026-10-27T22:10:00-05:00"
OBSERVED = "2026-10-27T21:00:00-05:00"
QUOTE = "2026-10-27T20:59:00-05:00"
DK_ID = "34901566"
FIXTURE = {
    "id": "espn-game-1", "date": "2026-10-28T03:10:00Z",
    "competitions": [{"competitors": [
        {"homeAway": "home", "team": {"id": "13", "displayName": "Los Angeles Lakers"}},
        {"homeAway": "away", "team": {"id": "22", "displayName": "Portland Trail Blazers"}},
    ]}],
}
ROSTERS = {
    "13": [{"athlete": {"id": "3945274", "displayName": "Luka Doncic"}}],
    "22": [{"athlete": {"id": "4433625", "displayName": "Scoot Henderson"}}],
}


def source(*, rosters=None, fixture=None):
    roster_data = ROSTERS if rosters is None else rosters
    event = FIXTURE if fixture is None else fixture

    def getter(url):
        if "scoreboard?" in url:
            return {"events": [event]}
        for tid in ("13", "22"):
            if url == NBA_ROSTER_URL.format(team_id=tid):
                if tid not in roster_data:
                    return None
                return {"team": {"id": tid}, "athletes": roster_data[tid]}
        return None

    return NBASource(getter=getter)


def row(**changes):
    out = {
        "sport": "NBA", "event_id": DK_ID, "capture_id": "cap-1",
        "book": "draftkings", "away": "Portland Trail Blazers",
        "home": "Los Angeles Lakers", "player_name": "Luka Doncic",
        "market": "PLAYER_POINTS", "side": "OVER", "line": 26.5,
        "odds": -110, "commence_time": TIP,
        "quote_captured_at": QUOTE,
    }
    out.update(changes)
    return out


def screen(rows=None, **kwargs):
    args = dict(
        source=source(), dk_event_id=DK_ID,
        away_name="Portland Trail Blazers",
        home_name="Los Angeles Lakers",
        scheduled_tipoff=TIP, observed_at=OBSERVED,
    )
    args.update(kwargs)
    return screen_nba_dk_player_rows([row()] if rows is None else rows, **args)


def test_matching_fixture_and_laker_roster_screen_only_no_admission():
    raw = row()
    original = copy.deepcopy(raw)
    result = screen([raw])
    assert raw == original
    assert result["accounting"] == {
        "raw_rows": 1, "screened_rows": 1,
        "rejected_rows": 0, "conservation_ok": True,
    }
    good = result["screened"][0]
    assert good["status"] == SCREEN_STATUS
    assert good["espn_event_id"] == FIXTURE["id"]
    assert good["espn_player_id"] == "3945274"
    assert good["espn_team_id"] == "13"
    assert good["quote_admitted"] is False
    assert result["forward_clock_authority"] is False
    assert result["requires_independent_pit_roster_archive"] is True
    assert "model_p" not in good and "ev_per_dollar" not in good


@pytest.mark.parametrize("change,reason", [
    ({"player_name": "Ja Morant"}, "NBA_DK_ROW_PLAYER_OR_TIMESTAMP_UNVERIFIED"),
    ({"event_id": "wrong-event"}, "NBA_DK_ROW_EVENT_MISMATCH"),
    ({"sport": "CFB"}, "NBA_DK_ROW_WRONG_SPORT"),
    ({"book": "espn"}, "NBA_DK_ROW_BOOK_UNVERIFIED"),
    ({"capture_id": ""}, "NBA_DK_ROW_CAPTURE_ID_MISSING"),
    ({"home": "Memphis Grizzlies"}, "NBA_DK_ROW_MATCHUP_MISMATCH"),
    ({"player_name": ""}, "NBA_DK_ROW_PLAYER_NAME_MISSING"),
    ({"quote_captured_at": "2026-10-27T23:00:00-05:00"},
     "NBA_DK_ROW_CLOCK_MISMATCH"),
    ({"quote_captured_at": "2026-10-27T20:59:00"},
     "NBA_DK_ROW_PLAYER_OR_TIMESTAMP_UNVERIFIED"),
    ({"commence_time": "2026-10-27T20:00:00-05:00"},
     "NBA_DK_ROW_CLOCK_MISMATCH"),
])
def test_cross_game_contamination_and_spoofs_are_rejected(change, reason):
    result = screen([row(**change)])
    assert result["screened"] == []
    assert result["rejected"][0]["reason"] == reason
    assert result["accounting"]["conservation_ok"] is True


def test_screen_keeps_all_rows_accounted_without_guessing_player_identity():
    result = screen([row(), row(player_name="Ja Morant"),
                     row(player_name="Scoot Henderson")])
    assert len(result["screened"]) == 2
    assert len(result["rejected"]) == 1
    assert {x["espn_team_id"] for x in result["screened"]} == {"13", "22"}
    assert result["accounting"]["conservation_ok"]


def test_missing_second_roster_cannot_admit_player_from_that_roster():
    result = screen([row(player_name="Scoot Henderson")],
                    source=source(rosters={"13": ROSTERS["13"]}))
    assert result["screened"] == []
    assert result["accounting"]["rejected_rows"] == 1


@pytest.mark.parametrize("alter", [
    {"id": ""},
    {"date": "2026-10-28T04:10:00Z"},
])
def test_fixture_identity_or_clock_failure_blocks_entire_batch(alter):
    fixture = copy.deepcopy(FIXTURE)
    fixture.update(alter)
    with pytest.raises(NBADataError):
        screen(source=source(fixture=fixture))


def test_no_post_tip_or_missing_provider_can_pass():
    with pytest.raises(NBADataError):
        screen(observed_at="2026-10-27T22:11:00-05:00")
    with pytest.raises(NBADataError):
        screen(source=source(rosters={}), away_name="Unknown Team")

def test_espn_team_id_and_name_cannot_be_crosswired():
    # A plausible team name on the wrong *valid* ESPN team ID is a
    # registry mismatch, not proof of fixture team identity.
    fixture = copy.deepcopy(FIXTURE)
    fixture["competitions"][0]["competitors"][0]["team"]["id"] = "29"
    with pytest.raises(NBADataError, match="NBA_DK_FIXTURE_TEAM_REGISTRY_MISMATCH"):
        screen(source=source(fixture=fixture))


def test_identical_player_name_across_both_rosters_refuses_ambiguity():
    both = copy.deepcopy(ROSTERS)
    both["22"].append({"athlete": {"id": "other-person", "displayName": "Luka Doncic"}})
    result = screen(source=source(rosters=both))
    assert result["screened"] == []
    assert result["rejected"][0]["reason"] == "NBA_DK_ROW_PLAYER_OR_TIMESTAMP_UNVERIFIED"
