"""Tests for sportsedge.live_run_it: phone-shaped live intake.

Network-free: a canned getter serves the live feed plus the ESPN endpoints
the pinned pregame-context reconstruction needs.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sportsedge.live_run_it import run_live_full

FIXTURES = Path(__file__).parent / "fixtures" / "live"
NOW = datetime(2026, 10, 11, 18, 40, tzinfo=timezone.utc)  # during the game
KICKOFF = datetime(2026, 10, 11, 0, 0, tzinfo=timezone.utc)

ESPN = "https://site.api.espn.com/apis/site/v2/sports"


def make_live_feed(*, source_as_of=None):
    """Recorded final feed mutated into a plausible live snapshot."""
    feed = json.loads((FIXTURES / "mlb_feed_final.json").read_text(encoding="utf-8"))
    feed["gameData"]["status"] = {
        "abstractGameState": "Live", "detailedState": "In Progress"}
    ls = feed["liveData"]["linescore"]
    ls["currentInning"] = 5
    ls["inningHalf"] = "Top"
    ls["outs"] = 1
    ls["balls"] = 2
    ls["strikes"] = 1
    ls["teams"] = {"away": {"runs": 3}, "home": {"runs": 1}}
    cp = feed["liveData"]["plays"]["currentPlay"]
    cp["about"] = {"inning": 5, "halfInning": "top"}
    cp["count"] = {"outs": 1, "balls": 2, "strikes": 1}
    # Provider timestamp: fresh by default; tests override for staleness.
    # Real StatsAPI format is %Y%m%d_%H%M%S (UTC).
    feed["metaData"]["timeStamp"] = (source_as_of or NOW).strftime(
        "%Y%m%d_%H%M%S")
    return feed


def canned_getter(feed):
    """Serve live feed + the ESPN endpoints used by pregame reconstruction."""
    scoreboard_date = KICKOFF.date().isoformat().replace("-", "")

    def _team(tid, name):
        return {"id": tid, "displayName": name, "name": name,
                "shortDisplayName": name, "abbreviation": name[:3].upper()}

    teams_payload = {"sports": [{"leagues": [{"teams": [
        {"team": _team("19", "Cleveland Guardians")},
        {"team": _team("14", "Chicago White Sox")},
    ]}]}]}

    def _completed(date_iso, pf, pa):
        return {"date": date_iso, "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"team": {"id": "19"}, "score": {"value": pf}},
                {"team": {"id": "99"}, "score": {"value": pa}},
            ]}]}

    schedule_payload = {"events": [
        _completed("2026-10-09T00:00:00Z", 5, 3),
        _completed("2026-10-08T00:00:00Z", 2, 4),
        _completed("2026-10-07T00:00:00Z", 6, 1),
        _completed("2026-10-06T00:00:00Z", 3, 3),
        _completed("2026-10-05T00:00:00Z", 4, 2),
    ]}

    scoreboard_payload = {"events": [{
        "id": "849831",
        "date": KICKOFF.isoformat(),
        "competitions": [{
            "status": {"type": {"state": "in"}},
            "competitors": [
                {"homeAway": "home",
                 "team": _team("19", "Cleveland Guardians")},
                {"homeAway": "away",
                 "team": _team("14", "Chicago White Sox")},
            ],
            "venue": {"id": "1"},
        }],
    }]}

    def get(url):
        if "game/849831/feed/live" in url:
            return copy.deepcopy(feed)
        if "/scoreboard" in url:
            return copy.deepcopy(scoreboard_payload)
        if "/teams?limit=500" in url:
            return copy.deepcopy(teams_payload)
        if "/schedule?season=" in url:
            return copy.deepcopy(schedule_payload)
        raise AssertionError("unexpected URL: " + url)

    return get


def line(**over):
    base = {"sport": "MLB", "market": "ML", "side": "HOME",
            "odds": -150, "game_pk": 849831}
    base.update(over)
    return base


def test_live_card_prices_game_market():
    card = run_live_full({"lines": [line()]}, now=NOW,
                         getter=canned_getter(make_live_feed()))
    assert card["schema"] == "SPORTSEDGE_LIVE_RESEARCH_CARD_V1"
    assert card["research_only"] is True
    assert card["authority"]["bet_execution"] is False
    row = card["evaluated_rows"][0]
    assert row["status"] in ("LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED",
                             "LIVE_BELOW_THRESHOLD")
    assert 0 < row["estimate_p"] < 1
    assert row["live_state_freshness"] == "FRESH"
    assert "Cleveland Guardians" in row["live_state"]
    assert row["market_blind"] is True
    assert row["model_validation"] == "NOT_PROVEN_VS_CLOSE"
    assert any(f["field"] == "mlb_bases_outs_count"
               for f in row["not_wired_live_fields"])
    # Factor coverage audit present for the priced row.
    audit = card["factor_coverage"]["by_input_index"][0]["factors"]
    assert audit["live_state"]["status"] == "VERIFIED_FRESH"
    assert audit["market_blind"]["status"] == "VERIFIED"


def test_live_card_player_prop_not_wired():
    card = run_live_full(
        {"lines": [line(market="PITCHER_STRIKEOUTS", side="OVER",
                        line=6.5, odds=-110)]},
        now=NOW, getter=canned_getter(make_live_feed()))
    row = card["evaluated_rows"][0]
    assert row["status"] == "NOT_WIRED_LIVE_PLAYER_PROP"
    assert "PITCHER" in row["reason"]


def test_live_card_first_inning_deferred():
    card = run_live_full({"lines": [line(market="NRFI", odds=-110)]},
                         now=NOW, getter=canned_getter(make_live_feed()))
    row = card["evaluated_rows"][0]
    assert row["status"] == "LIVE_FIRST_INNING_DEFERRED"
    assert "Phase 1" in row["reason"]


def test_live_card_final_game_blocked():
    feed = json.loads((FIXTURES / "mlb_feed_final.json").read_text(encoding="utf-8"))
    feed["metaData"]["timeStamp"] = NOW.strftime("%Y%m%d_%H%M%S")
    card = run_live_full({"lines": [line()]}, now=NOW,
                         getter=canned_getter(feed))
    row = card["evaluated_rows"][0]
    assert row["status"] == "GAME_NOT_LIVE"


def test_live_card_stale_provider_timestamp_blocked():
    from datetime import timedelta
    feed = make_live_feed(source_as_of=NOW - timedelta(seconds=61))
    card = run_live_full({"lines": [line()]}, now=NOW,
                         getter=canned_getter(feed))
    row = card["evaluated_rows"][0]
    assert row["status"] == "STALE_LIVE_DATA"
    assert "provider_timestamp" in row["reason"]


def test_live_card_stale_observed_at_blocked():
    # observed_at staleness is defense-in-depth for cached snapshots;
    # exercised at the state level (the poller clocks retrieval to the
    # card request, so the provider timestamp is the live signal).
    from datetime import timedelta
    from sportsedge.live_state import parse_mlb_live_feed
    when = NOW - timedelta(seconds=61)
    feed = make_live_feed(source_as_of=when)
    state = parse_mlb_live_feed(feed, retrieved_at=when, game_pk=849831)
    reason = state.staleness_reason(NOW)
    assert reason is not None and reason.startswith("STALE_LIVE_DATA")
    assert state.staleness_reason(when) is None


def test_live_card_no_bet_placement_fields():
    card = run_live_full({"lines": [line()]}, now=NOW,
                         getter=canned_getter(make_live_feed()))
    text = json.dumps(card)
    for token in ("kelly", "stake", "wager", "place_bet", "bet_slip"):
        assert token not in text.lower()


def test_live_card_spread_and_total():
    card = run_live_full({"lines": [
        line(market="SPREAD", side="HOME", line=-1.5, odds=-110),
        line(market="TOTAL", side="OVER", line=8.5, odds=-110),
    ]}, now=NOW, getter=canned_getter(make_live_feed()))
    for row in card["evaluated_rows"]:
        assert row["status"] in ("LIVE_RESEARCH_CANDIDATE_NOT_VALIDATED",
                                 "LIVE_BELOW_THRESHOLD")
        assert 0 <= row["estimate_p"] <= 1


# ---------------------------------------------------------------------------
# NFL with participation verification
# ---------------------------------------------------------------------------

NFL_NOW = datetime(2026, 10, 11, 23, 40, tzinfo=timezone.utc)
NFL_KICKOFF = datetime(2026, 10, 11, 20, 25, tzinfo=timezone.utc)


def nfl_canned_getter(summary_injuries):
    event = json.loads(
        (FIXTURES / "nfl_live_event.json").read_text(encoding="utf-8"))
    date_key = NFL_KICKOFF.date().isoformat().replace("-", "")

    def _team(tid, name, abbr):
        return {"id": tid, "displayName": name, "name": name,
                "shortDisplayName": name, "abbreviation": abbr}

    teams_payload = {"sports": [{"leagues": [{"teams": [
        {"team": _team("25", "San Francisco 49ers", "SF")},
        {"team": _team("26", "Seattle Seahawks", "SEA")},
    ]}]}]}

    def _completed(date_iso, pf, pa, tid):
        return {"date": date_iso, "competitions": [{
            "status": {"type": {"completed": True}},
            "competitors": [
                {"team": {"id": tid}, "score": {"value": pf}},
                {"team": {"id": "99"}, "score": {"value": pa}},
            ]}]}

    schedule_payload = {"events": [
        _completed("2026-10-04T20:25:00Z", 24, 20, "25"),
        _completed("2026-09-27T20:25:00Z", 17, 21, "25"),
        _completed("2026-09-20T20:25:00Z", 28, 14, "25"),
        _completed("2026-09-13T20:25:00Z", 20, 20, "25"),
        _completed("2026-09-06T20:25:00Z", 31, 17, "25"),
    ]}

    scoreboard_payload = {"events": [event]}

    def get(url):
        if "/summary?event=" in url:
            return {"injuries": copy.deepcopy(summary_injuries)}
        if "/scoreboard" in url:
            return copy.deepcopy(scoreboard_payload)
        if "/teams?limit=500" in url:
            return copy.deepcopy(teams_payload)
        if "/schedule?season=" in url:
            return copy.deepcopy(schedule_payload)
        if "/injuries" in url:
            return {"injuries": []}
        raise AssertionError("unexpected URL: " + url)

    return get


def nfl_line(**over):
    base = {"sport": "NFL", "market": "ML", "side": "HOME",
            "odds": -130, "event_id": "401872992"}
    base.update(over)
    return base


def _clean_injuries():
    payload = json.loads(
        (FIXTURES / "nfl_summary_injuries.json").read_text(encoding="utf-8"))
    return payload["injuries"]


def test_nfl_live_card_priced_with_clean_participation():
    card = run_live_full({"lines": [nfl_line()]}, now=NFL_NOW,
                         getter=nfl_canned_getter(_clean_injuries()))
    row = card["evaluated_rows"][0]
    # Priced, but held as WATCH under #2384 (Lane 1 audit): NFL live sides
    # never reach live_candidates.
    assert row["status"] == "LIVE_WATCH_NFL_SIDE_UNVALIDATED", row
    assert row["ev_per_dollar"] is not None
    assert card["live_candidates"] == []
    assert row["participation"]["check"] == "PARTICIPATION_OK"
    audit = card["factor_coverage"]["by_input_index"][0]["factors"]
    assert audit["participation"]["status"] == "VERIFIED_NO_MIDGAME_QB_CHANGE"


def test_nfl_live_card_blocked_on_midgame_qb_out():
    from datetime import timedelta
    injuries = _clean_injuries()
    for group in injuries:
        for entry in group["injuries"]:
            if entry["athlete"]["position"] == "QB" and entry["status"] == "Out":
                entry["date"] = (NFL_KICKOFF + timedelta(minutes=45)).isoformat()
                break
    card = run_live_full({"lines": [nfl_line()]}, now=NFL_NOW,
                         getter=nfl_canned_getter(injuries))
    row = card["evaluated_rows"][0]
    assert row["status"] == "LIVE_PARTICIPATION_CHANGE_UNPRICED"
    assert "QB" in row["reason"]


def test_nfl_live_card_blocked_when_participation_source_down():
    def get(url):
        if "/summary?event=" in url:
            raise ConnectionError("summary down")
        return nfl_canned_getter(_clean_injuries())(url)

    card = run_live_full({"lines": [nfl_line()]}, now=NFL_NOW, getter=get)
    row = card["evaluated_rows"][0]
    assert row["status"] == "LIVE_PARTICIPATION_UNVERIFIED"
