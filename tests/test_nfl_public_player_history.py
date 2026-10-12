"""ESPN 2026 seasonTypes/eventId regression and NFL phone-prop integration.

Stafford fixture uses the real date/id/stat values from the provided patch,
with unrelated ESPN presentation fields removed. Synthetic variations are
explicitly constructed in these tests.
"""
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sportsedge.nfl_public_player_history import MissingNFLHistory, NFLPlayerPublicSource
from artifacts.run_it_full import run_full

REAL = json.loads((Path(__file__).parent / "fixtures" / "nfl" /
                   "gamelog_stafford_12483_20261012_7games.json").read_text())
AWAY, HOME = "Buffalo Bills", "Los Angeles Rams"
KICKOFF = "2026-10-13T00:15:00+00:00"
AS_OF = "2026-10-12T21:50:00+00:00"
EXPECTED_PASS = [317.0, 390.0, 327.0, 155.0, 258.0, 304.0, 259.0]
EXPECTED_RUSH = [10.0, 13.0, -1.0, -1.0, -1.0, 0.0, 3.0]

ROSTERS = {
    "2": {"team": {"id": "2"}, "athletes": [{"items": [
        {"id": "3918298", "displayName": "Josh Allen"}]}]},
    "14": {"team": {"id": "14"}, "athletes": [{"items": [
        {"id": "12483", "displayName": "Matthew Stafford"}]}]},
}


def make_getter(gamelog):
    def getter(url):
        path = urlparse(url).path
        if path.endswith("/scoreboard"):
            return {"events": [{"id": "401873001", "date": KICKOFF,
                "competitions": [{"competitors": [
                    {"homeAway": "home", "team": {"id": "14", "displayName": HOME}},
                    {"homeAway": "away", "team": {"id": "2", "displayName": AWAY}},
                ]}]}]}
        if "/teams/" in path and path.endswith("/roster"):
            return ROSTERS.get(path.split("/teams/")[1].split("/")[0])
        if path.endswith("/gamelog"):
            return gamelog
        if path.endswith("/search/v2"):
            return {"results": []}
        raise AssertionError("Unexpected ESPN URL: " + url)
    return getter


def prior(gamelog, **kwargs):
    opts = dict(away=AWAY, home=HOME, player_name="Matthew Stafford",
                owner_kickoff=KICKOFF, as_of=AS_OF)
    opts.update(kwargs)
    return NFLPlayerPublicSource(getter=make_getter(gamelog)).prior_games(**opts)


def entries(gamelog):
    for st in gamelog.get("seasonTypes") or []:
        for cat in st.get("categories") or []:
            yield from cat.get("events") or []


def entry(gamelog, event_id):
    return next(e for e in entries(gamelog) if e.get("eventId") == event_id)


def test_seven_real_stafford_records_bind_passing_separately_from_rushing():
    out = prior(copy.deepcopy(REAL))
    assert out["player_id"] == "12483"
    assert out["prior_game_count"] == 7
    assert out["schema_rejected_prior_events"] == 0
    hist = out["features"]["game_history"]
    assert [g["passing_yards"] for g in hist] == EXPECTED_PASS
    assert [g["rushing_yards"] for g in hist] == EXPECTED_RUSH
    assert out["prior_game_times_utc"][0].startswith("2026-10-04")


def legacy(count=6):
    return {"names": ["completions", "passingAttempts", "passingYards"],
            "events": [{"id": str(401900000 + i),
                         "date": f"2026-09-{7+i:02d}T17:00:00Z",
                         "stats": ["20", "30", str(200 + 10*i)]}
                       for i in range(count)]}


def test_legacy_event_list_still_decodes():
    out = prior(legacy())
    assert [x["passing_yards"] for x in out["features"]["game_history"]] == [
        250., 240., 230., 220., 210., 200.]


def test_current_events_without_season_types_missing_not_zero_filled():
    data = copy.deepcopy(REAL)
    data.pop("seasonTypes")
    with pytest.raises(MissingNFLHistory, match="FEWER_THAN_FIVE"):
        prior(data)


def test_empty_categories_do_not_fake_games():
    data = copy.deepcopy(REAL)
    for st in data["seasonTypes"]:
        st["categories"] = []
    with pytest.raises(MissingNFLHistory, match="FEWER_THAN_FIVE"):
        prior(data)


def test_category_without_events_does_not_crash_or_create_false_history():
    data = copy.deepcopy(REAL)
    for st in data["seasonTypes"]:
        for cat in st["categories"]:
            cat.pop("events", None)
    with pytest.raises(MissingNFLHistory, match="FEWER_THAN_FIVE"):
        prior(data)


def test_conflicting_same_event_stats_fail_closed():
    data = copy.deepcopy(REAL)
    fake = list(entry(data, "401872970")["stats"])
    fake[2] = "999"
    data["seasonTypes"][0]["categories"].append(
        {"events": [{"eventId": "401872970", "stats": fake}]})
    with pytest.raises(MissingNFLHistory, match="ESPN_GAMELOG_STATS_CONFLICT"):
        prior(data)


def test_exact_duplicate_stats_are_safe_dedupe():
    data = copy.deepcopy(REAL)
    fake = list(entry(data, "401872970")["stats"])
    data["seasonTypes"][0]["categories"].append(
        {"events": [{"eventId": "401872970", "stats": fake}]})
    assert prior(data)["prior_game_count"] == 7


def test_duplicate_explicit_stat_names_make_schema_unusable():
    data = copy.deepcopy(REAL)
    data["names"][data["names"].index("rushingYards")] = "passingYards"
    with pytest.raises(MissingNFLHistory, match="FEWER_THAN_FIVE"):
        prior(data)


def test_mismatched_stats_array_is_rejected_not_zero_filled():
    data = copy.deepcopy(REAL)
    entry(data, "401872657")["stats"].pop()
    out = prior(data)
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] == 1
    assert 155 not in [x["passing_yards"] for x in out["features"]["game_history"]]


def test_non_numeric_named_stat_is_rejected_not_coerced():
    data = copy.deepcopy(REAL)
    entry(data, "401872657")["stats"][data["names"].index("passingYards")] = "N/A"
    out = prior(data)
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] == 1


def test_missing_game_date_is_rejected():
    data = copy.deepcopy(REAL)
    del data["events"]["401872657"]["gameDate"]
    out = prior(data)
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] == 1


def test_conflicting_metadata_key_and_id_are_rejected():
    data = copy.deepcopy(REAL)
    data["events"]["401872658"] = data["events"].pop("401872657")
    out = prior(data)
    assert out["prior_game_count"] == 6
    assert out["schema_rejected_prior_events"] >= 1


def test_future_and_post_asof_game_never_enter_history():
    data = copy.deepcopy(REAL)
    for eid,when in (("401873500", "2026-10-18T17:00:00+00:00"),
                     ("401873501", "2026-10-12T22:30:00+00:00")):
        data["events"][eid] = {"id": eid, "gameDate": when}
        fake = ["0"] * len(data["names"])
        fake[data["names"].index("passingYards")] = "999"
        data["seasonTypes"][0]["categories"][0]["events"].append(
            {"eventId": eid, "stats": fake})
    out = prior(data)
    assert out["prior_game_count"] == 7
    assert 999 not in [x["passing_yards"] for x in out["features"]["game_history"]]


def test_name_to_value_mapping_stats_variant():
    data = copy.deepcopy(REAL)
    for e in entries(data):
        e["stats"] = dict(zip(data["names"], e["stats"]))
    out = prior(data)
    assert out["prior_game_count"] == 7
    assert [x["passing_yards"] for x in out["features"]["game_history"]] == EXPECTED_PASS


def test_unsupported_event_shape_returns_specific_error():
    with pytest.raises(MissingNFLHistory, match="ESPN_GAMELOG_EVENTS_NOT_LIST"):
        prior({"names": REAL["names"], "events": "not an event collection"})


def test_full_phone_run_it_stafford_paired_props_are_watch_not_bets():
    now = datetime(2026, 10, 12, 21, 52, tzinfo=timezone.utc)
    def quote(side, price):
        return {"sport": "NFL", "away": AWAY, "home": HOME,
                "game": f"{AWAY} @ {HOME}", "kickoff": KICKOFF,
                "market": "PLAYER_PASSING_YARDS",
                "player_name": "Matthew Stafford", "side": side,
                "line": 278.5, "price": price, "book": "draftkings",
                "quote_captured_at": "2026-10-12T21:51:30+00:00"}
    card = run_full({"sport": "NFL", "lines": [quote("OVER",-111),
                     quote("UNDER",-113)]}, now=now,
                    getter=make_getter(copy.deepcopy(REAL)))
    assert not card["prop_unpriced"]
    rows = card["evaluated_rows"]
    assert len(rows) == 2
    # Both selections remain non-promoted; the positive-EV side is
    # participation-WATCH while the opposite side fails the EV floor first.
    assert all(row["status"].startswith("WATCH_") for row in rows)
    over = next(row for row in rows if row["selection"] == "OVER")
    under = next(row for row in rows if row["selection"] == "UNDER")
    assert over["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
    assert under["status"] == "WATCH_BELOW_EV_FLOOR"
    assert over["prior_game_count"] == 7
    assert over["model_probability"] == pytest.approx(4/7)
    assert over["stats_schema"] == "ESPN_EXPLICIT_NAMES_ONLY"
    receipts = [r for r in card["source_receipts"]
                if r.get("status") == "PUBLIC_NFL_PRIOR_GAMES_VERIFIED"]
    assert len(receipts) == 1 and receipts[0]["prior_games"] == 7
