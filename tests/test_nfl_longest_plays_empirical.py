"""Tests for the NFL longest-plays empirical engine (matrix
N25/N30/N31/N36).

QB longest completion / longest reception / longest rush / first
reception yardage from strictly-prior verified play-by-play
(nflverse). Research posture: the engine exists and is
unit-verified, but the canonical path still terminates the three
longest markets at GOVERNANCE_NO_ENGINE -- the governance surface
(config/football_prop_engine_surface.json) is not changed by the
engine's existence, and the coverage detail now names the engine
as wired-but-not-admitted (the kicking / anytime-TD precedent).
First reception has no canonical key at all, so it exists only as
a research readout. No card row may price from this engine. The
engine consumes no participation basis (#2274 untouched); its
distributions condition on >= 1 recorded opportunity, which the
readout declares.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_longest_plays_empirical import (
    ENGINE_ID,
    NflLongestPlaysError,
    build_longest_play_games,
    estimate_longest_plays,
    prob_over_under,
)

BASE = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
TARGET = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


def _rec(day_offset, player, role, plays, first_rec="ABSENT"):
    r = {"game_id": f"G{day_offset}", "player_id": player,
         "role": role, "team": "T",
         "kickoff": BASE + timedelta(days=day_offset),
         "play_yards": list(plays)}
    if first_rec != "ABSENT":
        r["first_reception_yards"] = first_rec
    else:
        r["first_reception_yards"] = plays[0] if plays else None
    return r


def _pool(player="P1", role="RECEIVER", plays=(6, 12, 9, 22), n=10,
          first_rec="ABSENT"):
    """Target player + two league peers, all strictly prior."""
    rows = []
    for i in range(n):
        rows.append(_rec(i * 7, player, role, plays, first_rec))
        rows.append(_rec(i * 7 + 1, "L1", role, (4, 8, 15), first_rec))
        rows.append(_rec(i * 7 + 2, "L2", role, (7, 18), first_rec))
    return rows


def test_pmfs_are_settlement_mass_exact():
    out = estimate_longest_plays(_pool(), player_id="P1",
                                 role="RECEIVER", kickoff=TARGET)
    assert out["engine"] == ENGINE_ID
    assert out["validation_status"] == "NOT_VALIDATED"
    assert out["market"] == "LONGEST_RECEPTION"
    assert out["conditioning"] == "AT_LEAST_ONE_OPPORTUNITY_RECORDED"
    assert out["games_used"] == 10
    for section in ("longest", "opportunities_per_game"):
        total = sum(out[section]["pmf"].values())
        assert total == pytest.approx(1.0, abs=1e-9), section
    fr = out["first_reception"]
    assert fr["market"] == "FIRST_RECEPTION"
    assert sum(fr["pmf"].values()) == pytest.approx(1.0, abs=1e-9)
    raw = out["trailing_raw_longest_pmf_diagnostic"]
    assert sum(raw.values()) == pytest.approx(1.0, abs=1e-9)


def test_longest_mean_tracks_play_yardage():
    deep = estimate_longest_plays(
        _pool(plays=(15, 28, 42, 9)), player_id="P1",
        role="RECEIVER", kickoff=TARGET)
    short = estimate_longest_plays(
        _pool(plays=(3, 5, 4, 6)), player_id="P1",
        role="RECEIVER", kickoff=TARGET)
    assert deep["longest"]["mean"] > short["longest"]["mean"] + 10
    over_deep = prob_over_under(deep["longest"]["pmf"], 24.5)[0]
    over_short = prob_over_under(short["longest"]["pmf"], 24.5)[0]
    assert over_deep > over_short


def test_max_statistic_concentrates_on_constant_plays():
    rows = []
    for i in range(8):
        for pid in ("P1", "L1", "L2"):
            rows.append(_rec(i * 7, pid, "PASSER", (20,) * 12))
    out = estimate_longest_plays(rows, player_id="P1", role="PASSER",
                                 kickoff=TARGET)
    assert out["market"] == "LONGEST_COMPLETION"
    assert out["longest"]["pmf"][20] == pytest.approx(1.0, abs=1e-9)
    assert out["longest"]["mean"] == pytest.approx(20.0, abs=1e-9)


def test_strict_pit_filtering():
    prior = estimate_longest_plays(_pool(), player_id="P1",
                                   role="RECEIVER", kickoff=TARGET)
    rows = _pool() + [
        _rec(400, "P1", "RECEIVER", (99, 99, 99)),
        _rec(401, "L1", "RECEIVER", (99, 99, 99)),
    ]
    after = estimate_longest_plays(rows, player_id="P1",
                                   role="RECEIVER", kickoff=TARGET)
    assert after == prior


def test_trailing_window_cap():
    rows = []
    for i in range(20):  # 3-day spacing keeps all 20 strictly prior
        rows.append(_rec(i * 3, "P1", "RECEIVER", (6, 12, 9, 22)))
        rows.append(_rec(i * 3 + 1, "L1", "RECEIVER", (4, 8, 15)))
        rows.append(_rec(i * 3 + 2, "L2", "RECEIVER", (7, 18)))
    out = estimate_longest_plays(rows, player_id="P1",
                                 role="RECEIVER", kickoff=TARGET)
    assert out["games_used"] == 16


def test_fail_closed_gates():
    with pytest.raises(NflLongestPlaysError, match="IDENTITY"):
        estimate_longest_plays(_pool(), player_id="", role="RECEIVER",
                               kickoff=TARGET)
    with pytest.raises(NflLongestPlaysError, match="ROLE_INVALID"):
        estimate_longest_plays(_pool(), player_id="P1", role="PUNTER",
                               kickoff=TARGET)
    with pytest.raises(NflLongestPlaysError, match="TIMEZONE"):
        estimate_longest_plays(_pool(), player_id="P1",
                               role="RECEIVER",
                               kickoff=datetime(2026, 11, 22, 18, 0))
    bad = _pool()
    bad[0] = dict(bad[0], kickoff=None)
    with pytest.raises(NflLongestPlaysError, match="KICKOFF_MISSING"):
        estimate_longest_plays(bad, player_id="P1", role="RECEIVER",
                               kickoff=TARGET)
    with pytest.raises(NflLongestPlaysError,
                       match="HISTORY_INSUFFICIENT"):
        estimate_longest_plays(_pool(n=3), player_id="P1",
                               role="RECEIVER", kickoff=TARGET)
    empty = [_rec(i * 7, "P1", "RUSHER", ()) for i in range(6)] + \
            [_rec(i * 7 + 1, "L1", "RUSHER", (3, 4)) for i in range(6)]
    with pytest.raises(NflLongestPlaysError, match="NO_PLAYS"):
        estimate_longest_plays(empty, player_id="P1", role="RUSHER",
                               kickoff=TARGET)


def test_prob_over_under_lines():
    pmf = {10: 0.25, 20: 0.5, 30: 0.25}
    assert prob_over_under(pmf, 20) == (0.25, 0.5, 0.25)
    assert prob_over_under(pmf, 20.5) == (0.25, 0.0, 0.75)


def test_estimate_is_deterministic():
    a = estimate_longest_plays(_pool(), player_id="P1",
                               role="RECEIVER", kickoff=TARGET)
    b = estimate_longest_plays(_pool(), player_id="P1",
                               role="RECEIVER", kickoff=TARGET)
    assert a == b


def test_first_reception_tracks_first_not_longest():
    rows = _pool(plays=(5, 40, 3, 8))
    out = estimate_longest_plays(rows, player_id="P1",
                                 role="RECEIVER", kickoff=TARGET)
    fr = out["first_reception"]
    assert fr["observations"] == 10
    # First receptions are all 5 (shrunk toward a league whose first
    # receptions are also 5); the longest is driven by the 40.
    assert fr["mean"] < 12
    assert out["longest"]["mean"] > 25
    passer = estimate_longest_plays(_pool(role="PASSER"),
                                    player_id="P1", role="PASSER",
                                    kickoff=TARGET)
    assert "first_reception" not in passer


def test_rusher_role_and_negative_plays():
    rows = _pool(role="RUSHER", plays=(-2, 4, 11, 3))
    out = estimate_longest_plays(rows, player_id="P1", role="RUSHER",
                                 kickoff=TARGET)
    assert out["market"] == "LONGEST_RUSH"
    assert sum(out["longest"]["pmf"].values()) == pytest.approx(
        1.0, abs=1e-9)
    neg = sum(v for k, v in out["longest"]["pmf"].items() if k < 0)
    assert 0.0 <= neg < 0.05  # longest is rarely negative, never NaN


def _frames():
    import pandas as pd

    games = pd.DataFrame([
        {"game_id": "2026_01_A_B", "gameday": "2026-09-13",
         "gametime": "13:00"},
    ])
    cols = ["game_id", "play_id", "posteam", "passer_player_id",
            "receiver_player_id", "rusher_player_id", "pass_attempt",
            "complete_pass", "rush_attempt", "yards_gained"]
    plays = [
        # completion Q1 -> W1 for 12 (W1's first reception)
        ["2026_01_A_B", 1, "A", "Q1", "W1", None, 1, 1, 0, 12],
        # incomplete: excluded everywhere
        ["2026_01_A_B", 2, "A", "Q1", "W1", None, 1, 0, 0, 0],
        # completion Q1 -> W1 for 30
        ["2026_01_A_B", 3, "A", "Q1", "W1", None, 1, 1, 0, 30],
        # rushes: R1 -3 then 8; Q1 scramble 5
        ["2026_01_A_B", 4, "A", None, None, "R1", 0, 0, 1, -3],
        ["2026_01_A_B", 5, "A", None, None, "R1", 0, 0, 1, 8],
        ["2026_01_A_B", 6, "A", None, None, "Q1", 0, 0, 1, 5],
        # game with no kickoff mapping: skipped, not fabricated
        ["2026_99_X_Y", 1, "X", "Q9", "W9", None, 1, 1, 0, 50],
    ]
    return pd.DataFrame(plays, columns=cols), games


def test_build_longest_play_games_from_pbp():
    pbp, games = _frames()
    records = build_longest_play_games(pbp, games)
    by = {(r["player_id"], r["role"]): r for r in records}
    assert by[("Q1", "PASSER")]["play_yards"] == [12, 30]
    w1 = by[("W1", "RECEIVER")]
    assert w1["play_yards"] == [12, 30]
    assert w1["first_reception_yards"] == 12
    assert by[("R1", "RUSHER")]["play_yards"] == [-3, 8]
    assert by[("Q1", "RUSHER")]["play_yards"] == [5]
    assert ("Q9", "PASSER") not in by
    assert all(r["kickoff"].tzinfo is not None for r in records)


def test_build_longest_play_games_schema_fail_closed():
    import pandas as pd

    pbp, games = _frames()
    with pytest.raises(NflLongestPlaysError, match="PBP_SCHEMA"):
        build_longest_play_games(pbp.drop(columns=["yards_gained"]),
                                 games)
    with pytest.raises(NflLongestPlaysError, match="GAMES_SCHEMA"):
        build_longest_play_games(pbp, games.drop(columns=["gametime"]))


def test_public_source_with_fake_fetcher():
    from sportsedge.nfl_longest_plays_empirical import (
        NflLongestPlaysPublicSource,
    )

    pbp, games = _frames()

    def fake(url, gz):
        return pbp if "play_by_play" in url else games

    src = NflLongestPlaysPublicSource(fetcher=fake)
    receivers = src.records_for([2026], role="RECEIVER")
    assert len(receivers) == 1
    assert receivers[0]["player_id"] == "W1"
    assert src.records_for([2026], role="PASSER")[0]["player_id"] \
        == "Q1"
    with pytest.raises(NflLongestPlaysError, match="ROLE_INVALID"):
        src.records_for([2026], role="PUNTER")


def test_canonical_path_still_refuses_at_governance_gate():
    from sportsedge.canonical_coverage import blocked_row_for

    row = {"market": "LONGEST_COMPLETION", "side": "OVER"}
    for market in ("LONGEST_COMPLETION", "LONGEST_RECEPTION",
                   "LONGEST_RUSH"):
        blocked = blocked_row_for("NFL", market, row)
        assert blocked is not None, market
        assert blocked["status"] == "NO_MODEL_OR_MARKET"
        assert blocked["blocker"] == "NO_ENGINE"
        assert "GOVERNANCE_NO_ENGINE" in blocked["blocker_detail"]
        for key in ("model_p", "model_probability", "ev",
                    "expected_value"):
            assert key not in blocked


def test_coverage_names_the_engine_not_admitted():
    from sportsedge.canonical_coverage import resolve_market

    for market in ("longest_completion", "longest_reception",
                   "longest_rush"):
        res = resolve_market("NFL", market)
        assert res["state"] == "BLOCKED"
        assert "NFL_LONGEST_PLAYS_EMPIRICAL" in (res["engine"] or "")
        assert "not admitted" in res["engine"]
    # targets is NOT part of this item: its refusal text is unchanged
    res = resolve_market("NFL", "targets")
    assert res["state"] == "BLOCKED"
    assert "NFL_LONGEST_PLAYS_EMPIRICAL" not in (res["engine"] or "")
