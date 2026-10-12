"""Recorded-fixture tests for the fail-closed NBA gamelog decoder."""
import json
from pathlib import Path

import pytest

from sportsedge.sports.nba.nba_gamelog_decode import (
    NBAGamelogSchemaError,
    decode_nba_gamelog_event,
    iter_gamelog_games,
)

FIX = Path(__file__).parent / "fixtures" / "nba"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class TestDecode:
    def test_decode_recorded_games(self):
        gamelog = load("gamelog_1966_2025.json")
        rows = {}
        for st_display, meta, cat_event in iter_gamelog_games(gamelog):
            assert "Regular Season" in st_display
            stats = decode_nba_gamelog_event(gamelog, cat_event)
            rows[stats["event_id"]] = stats
        # real recorded values: (MIN, PTS, REB, AST, 3PT-made)
        assert rows["401704684"]["minutes"] == 29
        assert rows["401704684"]["points"] == 26
        assert rows["401704684"]["rebounds"] == 6
        assert rows["401704684"]["assists"] == 3
        assert rows["401704684"]["threes_made"] == 1
        assert rows["401704677"]["points"] == 11
        assert rows["401704677"]["assists"] == 8
        assert rows["401704662"]["points"] == 32
        assert rows["401704662"]["rebounds"] == 14
        assert rows["401704662"]["assists"] == 10  # triple-double night

    def test_threes_made_parses_made_attempted_pair(self):
        gamelog = load("gamelog_1966_2025.json")
        names = gamelog["names"]
        idx = names.index("threePointFieldGoalsMade-threePointFieldGoalsAttempted")
        cat_event = {"eventId": "x", "stats": ["0"] * len(names)}
        cat_event["stats"][idx] = "4-9"
        for i, name in enumerate(names):
            canon = "".join(c for c in name.lower() if c.isalnum())
            if canon in {"minutes", "points", "totalrebounds", "assists",
                         "blocks", "steals", "fouls", "turnovers"}:
                cat_event["stats"][i] = "5"
        stats = decode_nba_gamelog_event(gamelog, cat_event)
        assert stats["threes_made"] == 4

    def test_events_dict_shape_required(self):
        with pytest.raises(NBAGamelogSchemaError):
            list(iter_gamelog_games({"events": [], "seasonTypes": []}))

    def test_names_stats_misaligned_fails_closed(self):
        gamelog = load("gamelog_1966_2025.json")
        bad = {"eventId": "x", "stats": ["1", "2"]}
        with pytest.raises(NBAGamelogSchemaError):
            decode_nba_gamelog_event(gamelog, bad)

    def test_total_categories_are_skipped(self):
        gamelog = load("gamelog_1966_2025.json")
        st = gamelog["seasonTypes"][0]
        st["categories"].append({"displayName": "Postseason", "type": "total",
                                 "splitType": "postseason", "totals": ["1"]})
        n = sum(1 for _ in iter_gamelog_games(gamelog))
        assert n == 3

    def test_missing_required_stat_fails_closed(self):
        gamelog = load("gamelog_1966_2025.json")
        names = [n for n in gamelog["names"] if n != "points"]
        trimmed = dict(gamelog, names=names)
        _, _, cat_event = next(iter(iter_gamelog_games(gamelog)))
        stats = [s for s, n in zip(cat_event["stats"], gamelog["names"]) if n != "points"]
        with pytest.raises(NBAGamelogSchemaError):
            decode_nba_gamelog_event(trimmed, {"eventId": cat_event["eventId"], "stats": stats})

    def test_event_meta_missing_fails_closed(self):
        gamelog = load("gamelog_1966_2025.json")
        gamelog = dict(gamelog, events={})
        with pytest.raises(NBAGamelogSchemaError):
            list(iter_gamelog_games(gamelog))
