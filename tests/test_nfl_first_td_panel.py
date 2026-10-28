"""First-TD attribution panel derivation tests.

Exercises the derivation rules pinned in build_panel.py against
synthetic play-by-play frames and the merged evidence layer
(sportsedge/nfl_first_td_pbp_evidence.py): defensive TD first,
field-goal-first games (the first TD is still the label), safeties
are not touchdowns, overtime first TDs, no-TD games, missing scorer
identity, out-of-order events, incomplete PBP, and the 2019 LV->OAK
team-code normalization.
"""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_BUILDER = (Path(__file__).resolve().parents[1]
            / "research" / "nfl_first_td_panel_20261028"
            / "build_panel.py")
_spec = importlib.util.spec_from_file_location("build_panel", _BUILDER)
bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bp)

from sportsedge.nfl_first_td_pbp_evidence import (  # noqa: E402
    first_td_from_complete_pbp,
)

COLS = ["play_id", "game_id", "qtr", "quarter_seconds_remaining",
        "posteam", "td_team", "td_player_id", "td_player_name",
        "touchdown", "pass_touchdown", "rush_touchdown",
        "return_touchdown", "interception", "play_type"]


def play(pid, qtr, qsr, **kw):
    row = {"play_id": pid, "game_id": "2099_01_AAA_BBB", "qtr": qtr,
           "quarter_seconds_remaining": qsr, "posteam": "AAA",
           "td_team": None, "td_player_id": None, "td_player_name": None,
           "touchdown": 0, "pass_touchdown": 0, "rush_touchdown": 0,
           "return_touchdown": 0, "interception": 0, "play_type": "run"}
    row.update(kw)
    return row


def base_plays(n_periods=4, total=120):
    """A structurally complete game skeleton (no TDs yet)."""
    rows = []
    pid = 0
    per = total // n_periods
    for q in range(1, n_periods + 1):
        for i in range(per):
            pid += 1
            rows.append(play(pid * 10, q, 900 - i * 25))
    return rows


def frame(rows):
    return pd.DataFrame(rows, columns=COLS)


def with_td(rows, idx, **kw):
    rows = [dict(r) for r in rows]
    rows[idx].update({"touchdown": 1, **kw})
    return rows


def game_row():
    return pd.Series({
        "game_id": "2099_01_AAA_BBB", "away_team": "AAA",
        "home_team": "BBB", "week": 1, "season_type": "REG",
        "gameday": pd.Timestamp("2099-09-10"), "gametime": "13:00"})


SHA = "a" * 64
OBS = "2100-01-01T00:00:00+00:00"


def label(rows):
    excl, ordered = bp.classify_game(frame(rows))
    assert excl is None, excl
    packet = bp.build_packet(game_row(), ordered, SHA, OBS)
    return first_td_from_complete_pbp(packet)


def test_defensive_td_first_is_credited_to_the_defender():
    rows = with_td(base_plays(), 5, td_team="BBB",
                   td_player_id="00-0099999", td_player_name="Def Ender",
                   return_touchdown=1, interception=1,
                   play_type="pass")
    cand = label(rows)
    assert cand.touchdown_found
    assert cand.credited_player_id == "00-0099999"
    assert cand.scoring_team_id == "BBB"
    assert cand.touchdown_type == "INTERCEPTION_RETURN"


def test_fg_first_game_still_labels_first_td():
    rows = base_plays()
    rows[3].update({"play_type": "field_goal"})  # a made FG, not a TD
    rows = with_td(rows, 40, td_team="AAA", td_player_id="00-0011111",
                   td_player_name="Run Back", rush_touchdown=1)
    cand = label(rows)
    assert cand.touchdown_found
    assert cand.credited_player_id == "00-0011111"
    assert cand.touchdown_type == "RUSHING"


def test_safety_is_not_a_touchdown():
    rows = base_plays()
    rows[7].update({"play_type": "punt"})  # safety happens elsewhere;
    # no touchdown flag is ever set for a safety in the feed
    cand = label(rows)
    assert not cand.touchdown_found


def test_overtime_first_td():
    rows = base_plays(n_periods=5)
    rows = with_td(rows, 110, td_team="BBB", td_player_id="00-0022222",
                   td_player_name="Ot Hero", pass_touchdown=1,
                   play_type="pass")
    cand = label(rows)
    assert cand.touchdown_found
    assert cand.credited_player_id == "00-0022222"
    assert cand.touchdown_type == "RECEIVING"


def test_return_types_map_to_evidence_taxonomy():
    cases = [
        ({"return_touchdown": 1, "interception": 1,
          "play_type": "pass"}, "INTERCEPTION_RETURN"),
        ({"return_touchdown": 1, "play_type": "kickoff"},
         "KICKOFF_RETURN"),
        ({"return_touchdown": 1, "play_type": "punt"}, "PUNT_RETURN"),
        ({"return_touchdown": 1, "play_type": "field_goal"},
         "BLOCKED_KICK_RETURN"),
        ({"return_touchdown": 1, "play_type": "run"}, "FUMBLE_RETURN"),
    ]
    for kw, expected in cases:
        row = {"pass_touchdown": 0, "rush_touchdown": 0,
               "return_touchdown": 0, "interception": 0,
               "play_type": "run", **kw}
        assert bp.td_type(row) == expected, kw


def test_missing_scorer_identity_excludes_game():
    rows = with_td(base_plays(), 10, td_team="AAA", td_player_id=None,
                   rush_touchdown=1)
    excl, _ = bp.classify_game(frame(rows))
    assert excl == "MISSING_SCORER_IDENTITY"


def test_out_of_order_events_excluded():
    # A touchdown play with no clock stamp cannot be placed in
    # event time: the game is excluded OUT_OF_ORDER_EVENTS.
    rows = with_td(base_plays(), 10, td_team="AAA",
                   td_player_id="00-0011111", rush_touchdown=1)
    rows[10]["quarter_seconds_remaining"] = None
    excl, _ = bp.classify_game(frame(rows))
    assert excl == "OUT_OF_ORDER_EVENTS"
    # A play with no period at all: same class.
    rows = base_plays()
    rows[3]["qtr"] = None
    excl, _ = bp.classify_game(frame(rows))
    assert excl == "OUT_OF_ORDER_EVENTS"


def test_incomplete_pbp_excluded():
    excl, _ = bp.classify_game(frame(base_plays()[:40]))
    assert excl == "INCOMPLETE_PBP"
    short_periods = [r for r in base_plays() if r["qtr"] <= 3]
    excl, _ = bp.classify_game(frame(short_periods))
    assert excl == "INCOMPLETE_PBP"


def test_team_code_normalization_2019_lv_to_oak():
    assert bp.TEAM_CODE_NORMALIZATION[(2019, "LV")] == "OAK"
