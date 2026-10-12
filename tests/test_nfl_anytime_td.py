"""Offline unit tests for sportsedge.nfl_anytime_td.

No network: history tables are built synthetically in-memory.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import pandas as pd
import pytest

from sportsedge.nfl_anytime_td import (
    NflTdError,
    assess_first_td,
    blocked_anytime_td,
    estimate_anytime_td,
    opponent_factor,
    position_priors,
    resolve_player_id,
    team_play_expectation,
)

UTC = timezone.utc


def _kicks(n, start="2025-09-07T17:00:00"):
    base = datetime.fromisoformat(start).replace(tzinfo=UTC)
    return [base + pd.Timedelta(days=7 * i) for i in range(n)]


def _history(*, player_tds=(1, 0, 2, 0, 1, 0), snap=0.65, pos="WR",
             n_games=6, team_games_extra=4, future_game=False):
    """Synthetic PIT-safe history for one player on team AAA vs BBB."""
    kicks = _kicks(n_games + (1 if future_game else 0))
    game_ids = [f"2025_{i:02d}_AAA_BBB" for i in range(len(kicks))]
    ps_rows = []
    for i, gid in enumerate(game_ids):
        rtd = player_tds[i] if i < len(player_tds) else 0
        ps_rows.append({
            "player_id": "00-001", "player_display_name": "Test Player",
            "position": pos, "position_group": pos, "season": 2025,
            "week": i + 1, "season_type": "REG", "game_id": gid,
            "team": "AAA", "opponent_team": "BBB",
            "carries": 2, "rushing_tds": 0, "targets": 6, "receptions": 4,
            "receiving_tds": rtd,
            "kickoff": kicks[i], "off_tds": rtd,
        })
    for i, gid in enumerate(game_ids):
        ps_rows.append({
            "player_id": "00-002", "player_display_name": "Other Back",
            "position": "RB", "position_group": "RB", "season": 2025,
            "week": i + 1, "season_type": "REG", "game_id": gid,
            "team": "AAA", "opponent_team": "BBB",
            "carries": 12, "rushing_tds": 1, "targets": 2, "receptions": 1,
            "receiving_tds": 0,
            "kickoff": kicks[i], "off_tds": 1,
        })
    player_stats = pd.DataFrame(ps_rows)

    tg_rows = []
    for i, gid in enumerate(game_ids):
        tg_rows.append({"game_id": gid, "team": "AAA", "kickoff": kicks[i],
                        "rush_atts": 25, "pass_atts": 35, "plays": 60,
                        "off_tds": 3, "rz_opps": 10.0,
                        "n_pass": 20, "n_rush": 15,
                        "neutral_pass_rate": 20 / 35})
        tg_rows.append({"game_id": gid, "team": "BBB", "kickoff": kicks[i],
                        "rush_atts": 28, "pass_atts": 32, "plays": 60,
                        "off_tds": 2, "rz_opps": 8.0,
                        "n_pass": 18, "n_rush": 16,
                        "neutral_pass_rate": 18 / 34})
    for j in range(team_games_extra):
        tg_rows.append({"game_id": f"2024_X{j}_AAA_CCC", "team": "AAA",
                        "kickoff": datetime(2024, 11, 1, tzinfo=UTC),
                        "rush_atts": 25, "pass_atts": 35, "plays": 60,
                        "off_tds": 3, "rz_opps": 9.0,
                        "n_pass": 20, "n_rush": 15,
                        "neutral_pass_rate": 20 / 35})
    team_games = pd.DataFrame(tg_rows)

    rz_rows = []
    for i, gid in enumerate(game_ids):
        rz_rows.append({"game_id": gid, "player_id": "00-001",
                        "kickoff": kicks[i], "rz_carries": 0.0,
                        "rz_targets": 2.0, "rz_opps": 2.0,
                        "rz_rush_tds": 0.0, "rz_rec_tds": 1.0, "rz_tds": 1.0})
        rz_rows.append({"game_id": gid, "player_id": "00-002",
                        "kickoff": kicks[i], "rz_carries": 3.0,
                        "rz_targets": 0.0, "rz_opps": 3.0,
                        "rz_rush_tds": 1.0, "rz_rec_tds": 0.0, "rz_tds": 1.0})
    rz_player = pd.DataFrame(rz_rows)

    idx = pd.MultiIndex.from_tuples(
        [(gid, "AAA", "test player") for gid in game_ids] +
        [(gid, "AAA", "other back") for gid in game_ids],
        names=["game_id", "team", "_norm_name"])
    snap_lookup = pd.Series([snap] * len(game_ids) * 2, index=idx)

    return {
        "player_stats": player_stats, "team_games": team_games,
        "rz_player": rz_player, "snap_lookup": snap_lookup,
        "proofs": [], "seasons": [2025],
    }


def _ko(history):
    return history["player_stats"]["kickoff"].max() + pd.Timedelta(days=7)


def _price(h, **kw):
    args = dict(player_id="00-001", player_name="Test Player", team="AAA",
                opponent="BBB", game_id="G", kickoff=_ko(h))
    args.update(kw)
    return estimate_anytime_td(h, **args)


def test_priced_probability_matches_poisson():
    out = _price(_history())
    assert out["status"] == "PRICED"
    assert out["market"] == "ANYTIME_TD"
    assert out["model_p"] == pytest.approx(1 - math.exp(-out["xtd"]))
    assert 0.0 < out["model_p"] < 1.0
    comps = out["components"]
    expect = (comps["x_rz_carries"] * comps["conv_rz_rush"]
              + comps["x_open_carries"] * comps["conv_open_rush"]
              + comps["x_rz_targets"] * comps["conv_rz_rec"]
              + comps["x_open_targets"] * comps["conv_open_rec"]) \
        * comps["opp_factor"]
    assert out["xtd"] == pytest.approx(expect)
    # ETR structure present in evidence
    assert "team plays" in out["evidence"]["etr_mapping"]


def test_insufficient_history_blocked():
    h = _history(n_games=3, player_tds=(1, 0, 0))
    with pytest.raises(NflTdError, match="TD_HISTORY_INSUFFICIENT"):
        _price(h)


def test_low_snap_share_blocked():
    h = _history(snap=0.10)
    with pytest.raises(NflTdError, match="TD_SNAP_SHARE_LOW"):
        _price(h)


def test_no_team_baseline_blocked():
    h = _history()
    h["team_games"] = h["team_games"].iloc[0:0]
    with pytest.raises(NflTdError, match="TD_NO_TEAM_BASELINE|TD_TEAM_BASELINE_THIN"):
        _price(h)


def test_unsupported_position_blocked():
    h = _history(pos="K")
    with pytest.raises(NflTdError, match="TD_POSITION_UNSUPPORTED"):
        _price(h)


def test_strict_pit_future_game_excluded():
    h = _history(n_games=6, future_game=True)
    ko = h["player_stats"]["kickoff"].max() - pd.Timedelta(hours=1)
    out = _price(h, kickoff=ko)
    assert out["n_games"] == 6  # the future game is excluded


def test_uncertainty_flags_sample_and_role():
    h = _history(n_games=6, snap=0.20)  # >= MIN_GAMES but < 8; snap < 0.30
    out = _price(h)
    assert "TD_SAMPLE_SMALL" in out["uncertainty_flags"]
    assert "TD_ROLE_UNCERTAIN" in out["uncertainty_flags"]


def test_opponent_factor_clamped():
    h = _history()
    f = opponent_factor(h, opponent="BBB", as_of=_ko(h))
    assert 0.6 <= f["opp_factor"] <= 1.6


def test_team_play_expectation_pass_run_split():
    h = _history()
    t = team_play_expectation(h, team="AAA", as_of=_ko(h))
    assert t["exp_rush_atts"] > 0 and t["exp_pass_atts"] > 0
    assert t["exp_rush_atts"] + t["exp_pass_atts"] == pytest.approx(t["exp_plays"])
    assert 0.0 < t["neutral_pass_rate"] < 1.0


def test_position_priors_have_all_components():
    h = _history()
    priors = position_priors(h, as_of=_ko(h))
    for pos in ("WR", "RB"):
        p = priors[pos]
        for key in ("carry_share", "target_share", "rz_carry_mix",
                    "rz_target_mix", "conv_rz_rush", "conv_open_rush",
                    "conv_rz_rec", "conv_open_rec"):
            assert 0.0 <= p[key] <= 1.0, (pos, key)
    assert priors["WR"]["target_share"] > priors["RB"]["target_share"]
    assert priors["RB"]["carry_share"] > priors["WR"]["carry_share"]


def test_resolve_player_id_and_ambiguity():
    h = _history()
    ko = _ko(h)
    assert resolve_player_id(h, display_name="Test Player", team="AAA", as_of=ko) == "00-001"
    with pytest.raises(NflTdError, match="TD_IDENTITY_UNRESOLVED"):
        resolve_player_id(h, display_name="Nobody Here", team="AAA", as_of=ko)
    dup = h["player_stats"].copy()
    extra = dup.iloc[[0]].copy()
    extra["player_id"] = "00-999"
    h2 = dict(h, player_stats=pd.concat([dup, extra], ignore_index=True))
    with pytest.raises(NflTdError, match="TD_IDENTITY_AMBIGUOUS"):
        resolve_player_id(h2, display_name="Test Player", team="AAA", as_of=ko)


def test_team_changer_uses_per_game_team_denominator():
    # Player's trailing games split across AAA and BBB: team totals must be
    # accumulated per game-team, not the fixture team.
    h = _history(n_games=6)
    ps = h["player_stats"]
    mask = (ps["player_id"] == "00-001") & (ps["week"] > 3)
    ps.loc[mask, "team"] = "BBB"
    ps.loc[mask, "opponent_team"] = "AAA"
    keys = [(str(r["game_id"]), str(r["team"]).upper(),
             "test player" if r["player_id"] == "00-001" else "other back")
            for _, r in ps.iterrows()]
    h["snap_lookup"] = pd.Series(
        [0.65] * len(keys), index=pd.MultiIndex.from_tuples(keys))
    out = _price(h)
    assert out["status"] == "PRICED"
    assert out["n_games"] == 6


def test_first_td_stays_blocked():
    v = assess_first_td()
    assert v["status"] == "BLOCKED"
    assert v["reason"] == "NO_VERIFIED_FIRST_SCORING_ATTRIBUTION"
    assert v["verifiable"] is False
    assert len(v["blockers"]) >= 3


def test_blocked_output_convention():
    b = blocked_anytime_td(player_name="X", game_id="G", team="AAA",
                           reason="TD_HISTORY_INSUFFICIENT:X:n=2")
    assert b["status"] == "NO_MODEL_OR_MARKET"
    assert b["market"] == "ANYTIME_TD"
    assert b["research_only"] is True
    assert b["staking_authority"] is False
