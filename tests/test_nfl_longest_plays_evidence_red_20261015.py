"""t181 Grok adversarial RED battery for #2341 (NFL longest plays /
first reception). Synthetic fixtures only; no real data, no
collectors. Engine stays research-only / NOT_VALIDATED / NO_ENGINE."""
import math
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from sportsedge.nfl_longest_plays_empirical import (
    Y_MAX, Y_MIN, NflLongestPlaysError, build_longest_play_games,
    estimate_longest_plays,
)

BASE = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
TARGET = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


def _rec(day, player, plays, role="RECEIVER", gid=None, first="AUTO"):
    return {"game_id": gid or f"G{day}", "player_id": player,
            "role": role, "team": "T",
            "kickoff": BASE + timedelta(days=day),
            "play_yards": list(plays),
            "first_reception_yards": (plays[0] if plays else None)
            if first == "AUTO" else first}


def _pool(n=8):
    rows = []
    for i in range(n):
        rows.append(_rec(i * 7, "P1", (6, 12, 9)))
        rows.append(_rec(i * 7 + 1, "L1", (-4, 8, 15)))
    return rows


def _est(rows, **kw):
    return estimate_longest_plays(rows, player_id="P1", role="RECEIVER",
                                  kickoff=TARGET, **kw)


def test_positive_clean_pool_accepted_and_pmf_sound():
    out = _est(_pool())
    pmf = out["longest"]["pmf"]
    assert math.isclose(math.fsum(pmf.values()), 1.0, abs_tol=1e-12)
    assert min(pmf) == Y_MIN and max(pmf) == Y_MAX
    assert sum(v for k, v in pmf.items() if k < 0) > 0  # negative support
    cdf, run = [], 0.0
    for k in sorted(pmf):
        run += pmf[k]
        cdf.append(run)
    assert all(b >= a - 1e-15 for a, b in zip(cdf, cdf[1:]))


def test_foreign_rows_never_enter_player_history():
    rows = _pool() + [_rec(60, "P2", (95,))]
    out = _est(rows)
    assert out["games_used"] == 8 and out["plays_used"] == 24


def test_missing_player_identity_on_pool_row_refuses():
    rows = _pool() + [_rec(61, "", (50,))]
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_PLAYER_ID_MISSING"):
        _est(rows)


def test_duplicate_player_game_refuses():
    rows = _pool() + [_rec(0, "P1", (6, 12, 9), gid="G0")]
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_DUPLICATE_GAME"):
        _est(rows)


def test_empty_play_list_row_refuses_not_zero_opportunity_mass():
    # An empty row would put P(N=0) mass at Y_MIN, contradicting the
    # declared >=1-opportunity conditioning.
    rows = _pool() + [_rec(62, "L1", ())]
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_PLAYS_EMPTY"):
        _est(rows)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"), 12.5, "x"])
def test_bad_play_yardage_refuses_with_named_code(bad):
    rows = _pool() + [_rec(63, "L1", (5, bad), first=5)]
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_YARDS_INVALID"):
        _est(rows)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 7.5])
def test_bad_first_reception_yardage_refuses(bad):
    rows = _pool() + [_rec(64, "L1", (5, 9), first=bad)]
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_YARDS_INVALID"):
        _est(rows)


def test_first_reception_not_among_plays_refuses():
    rows = _pool() + [_rec(65, "L1", (5, 9), first=40)]
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_FIRST_RECEPTION_INCONSISTENT"):
        _est(rows)


def test_naive_history_kickoff_refuses_with_named_code():
    r = _rec(66, "L1", (5,))
    r["kickoff"] = r["kickoff"].replace(tzinfo=None)
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_HISTORY_KICKOFF_TIMEZONE_REQUIRED"):
        _est(_pool() + [r])


def test_rows_at_or_after_kickoff_are_excluded():
    base = _est(_pool())
    rows = _pool() + [{**_rec(0, "P1", (99,), gid="GT"), "kickoff": TARGET},
                      {**_rec(0, "P1", (99,), gid="GA"),
                       "kickoff": TARGET + timedelta(days=1)}]
    out = _est(rows)
    assert out["games_used"] == base["games_used"]
    assert out["longest"]["pmf"] == base["longest"]["pmf"]


def _frames(yards):
    pbp = pd.DataFrame([{
        "game_id": "2026_01_A_B", "play_id": 1, "posteam": "A",
        "passer_player_id": "QB", "receiver_player_id": "WR",
        "rusher_player_id": None, "pass_attempt": 1,
        "complete_pass": 1, "rush_attempt": 0, "yards_gained": yards}])
    games = pd.DataFrame([{"game_id": "2026_01_A_B",
                           "gameday": "2026-09-13", "gametime": "13:00"}])
    return pbp, games


def test_source_keeps_measured_negative_yards():
    recs = build_longest_play_games(*_frames(-7))
    assert {r["role"]: r["play_yards"] for r in recs} == {
        "PASSER": [-7], "RECEIVER": [-7]}


def test_source_does_not_coerce_missing_yards_to_zero():
    with pytest.raises(NflLongestPlaysError,
                       match="LONGEST_PBP_YARDS_MISSING"):
        build_longest_play_games(*_frames(float("nan")))
