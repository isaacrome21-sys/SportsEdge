"""Tests for the NFL kicking empirical engine (matrix N43/N44/N45).

FG made / PAT made / kicking points from strictly-prior verified
kicking history (nflverse play-by-play). Research posture: the
engine exists and is unit-verified, but the canonical path still
terminates all three markets at GOVERNANCE_NO_ENGINE -- the
governance surface (config/football_prop_engine_surface.json) is
not changed by the engine's existence, and the coverage detail
now names the engine as wired-but-not-admitted (the anytime-TD /
passing-yards precedent). No card row may price from this engine.
"""
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.nfl_kicking_empirical import (
    ENGINE_ID,
    NflKickingError,
    build_kicking_games,
    estimate_kicking,
    prob_over_under,
)

BASE = datetime(2026, 9, 13, 17, 0, tzinfo=timezone.utc)
TARGET = datetime(2026, 11, 22, 18, 0, tzinfo=timezone.utc)


def _game(day_offset, fg, pat_att=2, pat_made=2, kid="K1"):
    return {"game_id": f"G{day_offset}", "kicker_id": kid,
            "kickoff": BASE + timedelta(days=day_offset),
            "fg_attempts": list(fg),
            "pat_attempts": pat_att, "pat_makes": pat_made}


def _history(n=10, fg=((35, True), (44, True), (52, False)), **kw):
    return [_game(i * 7, fg, **kw) for i in range(n)]


def test_pmfs_are_settlement_mass_exact():
    out = estimate_kicking(_history(), kicker_id="K1", kickoff=TARGET)
    assert out["engine"] == ENGINE_ID
    assert out["validation_status"] == "NOT_VALIDATED"
    assert out["games_used"] == 10
    for key in ("fg_made", "xp_made", "kicking_points"):
        total = sum(out[key]["pmf"].values())
        assert total == pytest.approx(1.0, abs=1e-12), key
    kp = out["kicking_points"]
    assert kp["mean"] == pytest.approx(
        3 * out["fg_made"]["mean"] + out["xp_made"]["mean"], abs=1e-9)
    assert sum(kp["trailing_raw_pmf_diagnostic"].values()) == \
        pytest.approx(1.0, abs=1e-12)


def test_means_track_the_kicker_record():
    strong = estimate_kicking(
        _history(fg=((30, True), (35, True), (40, True))),
        kicker_id="K1", kickoff=TARGET)
    weak = estimate_kicking(
        _history(fg=((55, False), (58, False))),
        kicker_id="K1", kickoff=TARGET)
    assert strong["fg_made"]["mean"] > weak["fg_made"]["mean"]
    assert strong["p_attempt_make"] > weak["p_attempt_make"]
    assert 0.5 < strong["p_attempt_make"] <= 1.0
    assert weak["p_pat_make"] == pytest.approx(
        strong["p_pat_make"])  # same PAT record in both histories


def test_band_rates_shrink_toward_league_not_extremes():
    # One made 62-yarder in the window: the 60+ band rate must sit
    # strictly between the league prior (0.420) and the raw 1.0.
    games = _history(fg=((25, True),))
    games[0]["fg_attempts"] = [(62, True), (25, True)]
    out = estimate_kicking(games, kicker_id="K1", kickoff=TARGET)
    rate = out["band_make_rates"]["60-+"]
    assert 0.420 < rate < 1.0


def test_strict_pit_filtering():
    games = _history()
    games.append(_game(200, ((30, True),) * 6))  # after TARGET
    games.append({"game_id": "GX", "kicker_id": "K1",
                  "kickoff": TARGET,  # AT kickoff: excluded
                  "fg_attempts": [(30, True)] * 6,
                  "pat_attempts": 6, "pat_makes": 6})
    out = estimate_kicking(games, kicker_id="K1", kickoff=TARGET)
    assert out["games_used"] == 10


def test_fail_closed_gates():
    with pytest.raises(NflKickingError, match="KICKING_IDENTITY"):
        estimate_kicking(_history(), kicker_id="", kickoff=TARGET)
    with pytest.raises(NflKickingError, match="TIMEZONE"):
        estimate_kicking(_history(), kicker_id="K1",
                         kickoff=datetime(2026, 11, 22, 18, 0))
    with pytest.raises(NflKickingError, match="INSUFFICIENT"):
        estimate_kicking(_history(n=4), kicker_id="K1", kickoff=TARGET)
    with pytest.raises(NflKickingError, match="NO_FG_ATTEMPTS"):
        estimate_kicking(_history(fg=()), kicker_id="K1", kickoff=TARGET)
    bad = _history()
    del bad[0]["kickoff"]
    with pytest.raises(NflKickingError, match="KICKOFF_MISSING"):
        estimate_kicking(bad, kicker_id="K1", kickoff=TARGET)


def test_prob_over_under_lines():
    pmf = {0: 0.1, 1: 0.2, 2: 0.4, 3: 0.3}
    over, push, under = prob_over_under(pmf, 1.5)
    assert push == 0.0
    assert over == pytest.approx(0.7) and under == pytest.approx(0.3)
    over, push, under = prob_over_under(pmf, 2)
    assert push == pytest.approx(0.4)
    assert over + push + under == pytest.approx(1.0)


def test_estimate_is_deterministic():
    a = estimate_kicking(_history(), kicker_id="K1", kickoff=TARGET)
    b = estimate_kicking(_history(), kicker_id="K1", kickoff=TARGET)
    assert a == b


def _frames():
    import pandas as pd

    pbp = pd.DataFrame([
        # game 1: made 35, missed 52, PAT good
        {"game_id": "2026_01_A_B", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 1, "field_goal_result": "made",
         "kick_distance": 35, "extra_point_attempt": 0,
         "extra_point_result": None},
        {"game_id": "2026_01_A_B", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 1, "field_goal_result": "no_good",
         "kick_distance": 52, "extra_point_attempt": 0,
         "extra_point_result": None},
        {"game_id": "2026_01_A_B", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 0, "field_goal_result": None,
         "kick_distance": None, "extra_point_attempt": 1,
         "extra_point_result": "good"},
        # game 1: blocked 45 counts as an attempt, not a make;
        # PAT failed
        {"game_id": "2026_01_A_B", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 1, "field_goal_result": "blocked",
         "kick_distance": 45, "extra_point_attempt": 0,
         "extra_point_result": None},
        {"game_id": "2026_01_A_B", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 0, "field_goal_result": None,
         "kick_distance": None, "extra_point_attempt": 1,
         "extra_point_result": "failed"},
        # kickoff-only appearance: no record may be created
        {"game_id": "2026_02_A_C", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 0, "field_goal_result": None,
         "kick_distance": None, "extra_point_attempt": 0,
         "extra_point_result": None},
        # game not in the games frame: dropped (no PIT kickoff)
        {"game_id": "2099_01_X_Y", "kicker_player_id": "K1",
         "kicker_player_name": "Kick One", "posteam": "A",
         "field_goal_attempt": 1, "field_goal_result": "made",
         "kick_distance": 30, "extra_point_attempt": 0,
         "extra_point_result": None},
    ])
    games = pd.DataFrame([
        {"game_id": "2026_01_A_B", "gameday": "2026-09-13",
         "gametime": "13:00"},
        {"game_id": "2026_02_A_C", "gameday": "2026-09-20",
         "gametime": "13:00"},
    ])
    return pbp, games


def test_build_kicking_games_from_pbp():
    pbp, games = _frames()
    records = build_kicking_games(pbp, games)
    assert len(records) == 1
    rec = records[0]
    assert rec["kicker_id"] == "K1" and rec["team"] == "A"
    assert rec["fg_attempts"] == [(35.0, True), (52.0, False),
                                  (45.0, False)]
    assert rec["pat_attempts"] == 2 and rec["pat_makes"] == 1
    assert rec["kickoff"].tzinfo is not None


def test_build_kicking_games_schema_fail_closed():
    import pandas as pd

    with pytest.raises(NflKickingError, match="SCHEMA_MISSING"):
        build_kicking_games(pd.DataFrame({"game_id": []}),
                            pd.DataFrame({"game_id": [],
                                          "gameday": [],
                                          "gametime": []}))


def test_public_source_with_fake_fetcher():
    from sportsedge.nfl_kicking_empirical import NflKickingPublicSource

    pbp, games = _frames()

    def fake(url, gz):
        return pbp if "play_by_play" in url else games

    src = NflKickingPublicSource(fetcher=fake)
    records = src.games_for([2026], kicker_id="K1")
    assert len(records) == 1
    assert src.games_for([2026], kicker_id="NOPE") == []


def test_canonical_path_still_refuses_at_governance_gate():
    from sportsedge.canonical_coverage import blocked_row_for

    row = {"market": "FG_MADE", "side": "OVER"}
    for market in ("FG_MADE", "KICKING_POINTS", "XP_MADE"):
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

    for market in ("fg_made", "kicking_points", "xp_made"):
        res = resolve_market("NFL", market)
        assert res["state"] == "BLOCKED"
        assert "NFL_KICKING_EMPIRICAL" in (res["engine"] or "")
        assert "not admitted" in res["engine"]
