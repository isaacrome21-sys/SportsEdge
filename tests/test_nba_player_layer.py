"""Leakage/consistency/status tests for the NBA player layer (synthetic unit inputs)."""
import random
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sportsedge.sports.nba.player_layer import (
    Availability, PlayerLog, allocate, build_rotation, player_market)
from sportsedge.sports.nba.quarter_joint_sim import QuarterGame, calibrate, simulate

T0 = datetime(2024, 11, 1, 23, 0, tzinfo=timezone.utc)
AS_OF = T0 + timedelta(days=12)
PIDS = [f"p{i}" for i in range(9)]


def logs(days=15, seed=4):
    rng = random.Random(seed)
    out = []
    for d in range(days):
        for i, p in enumerate(PIDS):
            m = max(0, 36 - 4 * i + rng.randint(-3, 3))
            out.append(PlayerLog(p, "BOS", f"g{d}", T0 + timedelta(days=d), m,
                                 rng.randint(0, 30 - 2 * i), rng.randint(0, 10), rng.randint(0, 8)))
    return out


def _sig(r):
    return (tuple(r.players), tuple(np.round(r.exp_minutes, 12)), tuple(np.round(r.ppm, 12)),
            r.reb_per_pt, r.ast_per_pt)


def test_future_and_order_do_not_change_rotation():
    g = logs()
    base = _sig(build_rotation(g, "BOS", AS_OF))
    sh = g[:]
    random.Random(2).shuffle(sh)
    fut = [PlayerLog("p0", "BOS", "fut", AS_OF + timedelta(hours=1), 48, 80, 30, 20),
           PlayerLog("new", "BOS", "fut", AS_OF, 48, 80, 30, 20)]
    assert _sig(build_rotation(sh + fut, "BOS", AS_OF)) == base


def test_minutes_sum_to_240_and_out_player_gets_zero():
    av = {"p0": Availability("OUT", "nba_official_injury_report", AS_OF - timedelta(hours=2))}
    r = build_rotation(logs(), "BOS", AS_OF, availability=av)
    assert r.exp_minutes.sum() == pytest.approx(240)
    assert r.exp_minutes[r.players.index("p0")] == 0


def test_player_totals_equal_joint_sim_team_totals_on_every_path():
    rng = random.Random(1)
    qg = [QuarterGame(str(i), T0 - timedelta(days=60) + timedelta(hours=i),
                      tuple(rng.randint(22, 34) for _ in range(4)) + (10,),
                      tuple(rng.randint(22, 34) for _ in range(4)) + (8,)) for i in range(40)]
    cal = calibrate(qg, AS_OF)
    H, _ = simulate(cal, 114, 108, n=300, seed=2)
    team = H.sum(1)
    r = build_rotation(logs(), "BOS", AS_OF)
    a = allocate(r, team, seed=1)
    assert np.array_equal(a["points"].sum(1), team)
    assert np.array_equal(a["rebounds"].sum(1), a["team_rebounds"])
    assert np.array_equal(a["assists"].sum(1), a["team_assists"])


def test_status_never_play_and_unknown_or_late_evidence_blocks():
    av = {"p1": Availability("AVAILABLE", "report", AS_OF + timedelta(minutes=1)),
          "p2": Availability("AVAILABLE", "nba_official_injury_report", AS_OF - timedelta(hours=1)),
          "p3": Availability("AVAILABLE", None, AS_OF - timedelta(hours=1))}
    r = build_rotation(logs(), "BOS", AS_OF, availability=av)
    a = allocate(r, np.full(500, 112), seed=3)
    s = {p: player_market(r, a, p, "PTS", 15.5)["status"] for p in ("p0", "p1", "p2", "p3")}
    assert s == {"p0": "BLOCKED", "p1": "BLOCKED", "p2": "WATCH", "p3": "BLOCKED"}
    assert all(player_market(r, a, p, "PRA", 20)["play_authority"] is False for p in PIDS)
    assert player_market(r, a, "ghost", "PTS", 10)["status"] == "BLOCKED"


def test_whole_line_push_mass():
    r = build_rotation(logs(), "BOS", AS_OF)
    a = allocate(r, np.full(2000, 110), seed=5)
    m = player_market(r, a, "p0", "PTS", 20.0)
    assert m["push"] > 0 and m["over"] + m["push"] <= 1
