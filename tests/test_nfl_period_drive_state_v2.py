"""Tests for NFL_PERIOD_DRIVE_STATE_V2's design screen
(research/nfl_period_drive_state_screen_20261028).

The design fixes the state buckets (section 3.2) before any run;
these tests pin the bucket boundaries exactly as written, the
simulator's determinism under its pre-declared seeds, the
point-in-time sample discipline of the team-rate book (a game
never sees itself or later games), the shrinkage direction, and
the screen's leg arithmetic on synthetic rows. Data-light: the
league fit and simulator are exercised on a synthetic play frame,
never on the pulled PBP.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
_MOD_PATH = (REPO_ROOT / "research" / "nfl_period_drive_state_screen_20261028"
             / "screen_nfl_period_drive_state_v2.py")
spec = importlib.util.spec_from_file_location("nfl_period_v2_screen",
                                              _MOD_PATH)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


# ------------------------------------------------------------------
# Section 3.2 state buckets - boundaries exactly as designed
# ------------------------------------------------------------------
def test_diff_bucket_boundaries():
    cases = {-40: 0, -17: 0, -16: 1, -9: 1, -8: 2, -3: 2, -2: 3,
             0: 3, 2: 3, 3: 4, 8: 4, 9: 5, 16: 5, 17: 6, 40: 6}
    for diff, want in cases.items():
        assert m.diff_bucket(diff) == want, diff


def test_time_bucket_boundaries():
    cases = {3600: 0, 1801: 0, 1800: 1, 901: 1, 900: 2, 301: 2,
             300: 3, 121: 3, 120: 4, 1: 4}
    for gsr, want in cases.items():
        assert m.time_bucket(gsr) == want, gsr


def test_quarter_of_score_timestamps():
    # A score at exactly a boundary belongs to the expiring quarter;
    # the halftime clamp value 1800 must land in Q2 (index 1).
    cases = {3599: 0, 2700: 0, 2699: 1, 1800: 1, 1799: 2, 900: 2,
             899: 3, 0: 3}
    for gsr, want in cases.items():
        assert m.quarter_of(gsr) == want, gsr


# ------------------------------------------------------------------
# Synthetic league fit + simulator determinism
# ------------------------------------------------------------------
def _synthetic_plays(n_games: int = 24, seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    pid = 0
    for g in range(n_games):
        gid = f"synth_{g:03d}"
        home, away = "AAA", "BBB"
        for drive in range(22):
            team = home if drive % 2 == 0 else away
            opp = away if team == home else home
            x = float(rng.integers(15, 45))
            for _ in range(rng.integers(3, 9)):
                pid += 1
                is_pass = rng.random() < 0.55
                gain = float(rng.integers(-5, 25)) if is_pass \
                    else float(rng.integers(-3, 15))
                rows.append({
                    "game_id": gid, "play_id": pid, "season": 2022,
                    "week": 1 + g % 18, "posteam": team, "defteam": opp,
                    "home_team": home, "away_team": away,
                    "play_type": "pass" if is_pass else "run",
                    "is_scrimmage": True,
                    "family": 1 if is_pass else 0,
                    "down": int(rng.integers(1, 5)),
                    "ydstogo": float(rng.integers(1, 15)),
                    "yardline_100": 100.0 - x,
                    "game_seconds_remaining": float(
                        rng.integers(60, 3600)),
                    "pre_diff": float(rng.integers(-21, 22)),
                    "diff_b": m.diff_bucket(
                        float(rng.integers(-21, 22))),
                    "time_b": int(rng.integers(0, 5)),
                    "pass_attempt": 1 if is_pass else 0,
                    "complete_pass": 1 if (is_pass
                                           and rng.random() < 0.62) else 0,
                    "sack": 1 if (is_pass and rng.random() < 0.07) else 0,
                    "interception": 1 if (is_pass
                                          and rng.random() < 0.02) else 0,
                    "fumble_lost": 1 if rng.random() < 0.008 else 0,
                    "yards_gained": gain,
                    "sec_consumed": float(rng.integers(4, 45)),
                    "penalty": 0, "penalty_team": None,
                    "penalty_yards": np.nan, "first_down_penalty": 0,
                    "extra_point_result": None,
                    "two_point_conv_result": None,
                    "safety": 0, "touchdown": 0,
                    "field_goal_result": None,
                    "fixed_drive": drive,
                    "fixed_drive_result": "Punt",
                    "goal_to_go": 0, "qb_scramble": 0,
                })
                x += gain
                if x >= 100 or x <= 0:
                    break
    d = pd.DataFrame(rows)
    d["diff_b"] = [m.diff_bucket(v) for v in d["pre_diff"]]
    d["time_b"] = [m.time_bucket(v)
                   for v in d["game_seconds_remaining"]]
    return d


def _synthetic_starts(plays: pd.DataFrame) -> pd.DataFrame:
    rng = np.random.default_rng(5)
    games = plays["game_id"].unique()
    rows = []
    for gid in games:
        for drive in range(22):
            rows.append({"game_id": gid, "fixed_drive": drive,
                         "team": "AAA" if drive % 2 == 0 else "BBB",
                         "x_start": float(rng.integers(10, 45)),
                         "season": 2022})
    return pd.DataFrame(rows)


def _blank_bundle(starts: tuple) -> dict:
    b = {k: 1.0 for k in (
        "rush_factor", "pass_factor", "comp_factor", "sack_factor",
        "int_factor", "fum_factor", "rush_allowed_factor",
        "pass_allowed_factor", "sack_made_factor", "takeaway_factor",
        "pen_factor", "pace_ratio", "rz_factor")}
    b.update({"starts": starts, "n_sample_games": 0,
              "league": m.league_rates({k: 0.0 for k in m._LEAGUE_KEYS})})
    return b


def test_simulator_deterministic_and_finite(monkeypatch):
    monkeypatch.setattr(m, "R_REPS", 400)
    plays = _synthetic_plays()
    starts = _synthetic_starts(plays)
    fit = m.LeagueFit(plays, starts)
    bundle = _blank_bundle(tuple(starts["x_start"][:80]))
    r1 = np.random.default_rng(np.random.SeedSequence([m.SEED_A, 0]))
    out1 = m.simulate_game(fit, bundle, bundle, r1)
    r2 = np.random.default_rng(np.random.SeedSequence([m.SEED_A, 0]))
    out2 = m.simulate_game(fit, bundle, bundle, r2)
    assert np.array_equal(out1["home_q"], out2["home_q"])
    assert np.array_equal(out1["away_q"], out2["away_q"])
    assert out1["unfinished"] == 0
    assert (out1["home_q"] >= 0).all() and (out1["away_q"] >= 0).all()
    r3 = np.random.default_rng(np.random.SeedSequence([m.SEED_B, 0]))
    out3 = m.simulate_game(fit, bundle, bundle, r3)
    assert not np.array_equal(out1["home_q"], out3["home_q"])


# ------------------------------------------------------------------
# Point-in-time discipline of the team-rate book
# ------------------------------------------------------------------
def _agg_frame() -> pd.DataFrame:
    rows = []
    for i in range(12):
        for team, other in (("AAA", "BBB"), ("BBB", "AAA")):
            row = {k: 0.0 for k in m._LEAGUE_KEYS}
            row.update({
                "game_id": f"g{i:02d}", "team": team,
                "season": 2023 if i < 6 else 2024, "week": i + 1,
                "n_run": 30.0, "run_yards": 300.0 if team == "AAA"
                else 90.0,
                "n_pass_att": 35.0, "pass_yards": 240.0,
                "n_complete": 22.0, "n_sack": 2.0, "int_thrown": 1.0,
                "fum_lost": 0.5, "n_scrim": 65.0, "pen_plays": 4.0,
                "sec_neutral": 800.0, "n_sec_neutral": 30.0,
                "n_run_faced": 30.0, "run_yards_allowed": 130.0,
                "n_pass_faced": 35.0, "pass_yards_allowed": 230.0,
                "sacks_made": 2.0, "takeaways": 1.5,
                "rz_trips": 4.0, "rz_tds": 3.0,
                "n_drives": 11.0, "starts_list": (25.0, 30.0),
            })
            rows.append(row)
    return pd.DataFrame(rows)


def test_bundle_never_sees_current_or_future_games():
    book = m.TeamRateBook(_agg_frame(), None)
    # No games recorded: every factor is exactly the league prior.
    b0 = book.bundle("AAA", 2023)
    assert b0["n_sample_games"] == 0
    assert b0["rush_factor"] == 1.0
    # Record g00..g02, then price g03: sample is exactly those 3.
    for i in range(3):
        book.record_game(f"g{i:02d}")
    b1 = book.bundle("AAA", 2023)
    assert b1["n_sample_games"] == 3
    # AAA runs for 10.0 yds/play in-sample vs a weaker league:
    # the factor must move UP from 1, toward but not past the raw
    # ratio (shrinkage).
    assert 1.0 < b1["rush_factor"] <= 10.0 / (
        b1["league"]["rush_ypp"])


def test_sample_rule_supplements_from_prior_season():
    book = m.TeamRateBook(_agg_frame(), None)
    for i in range(12):
        book.record_game(f"g{i:02d}")
    # Pricing a 2024 game: same-season sample is g06..g11 (6 games),
    # supplemented by the 2 most recent 2023 games to reach 8.
    b = book.bundle("BBB", 2024)
    assert b["n_sample_games"] == 8


# ------------------------------------------------------------------
# Screen leg arithmetic on synthetic rows
# ------------------------------------------------------------------
def _eval_df(m_scale: float) -> pd.DataFrame:
    rows = []
    rng = np.random.default_rng(11)
    for i in range(60):
        real = np.array([7.0, 10.0, 6.0, 8.0]) + rng.normal(0, 1, 4)
        mu = float(real.sum())
        share = np.array([0.22, 0.33, 0.20, 0.25])
        rows.append({"game_id": f"e{i}", "season": 2023 + i % 3,
                     "week": 1, "team": "AAA", "mu": mu,
                     "real_q": real, "b0_q": mu * share,
                     "b1_q": mu * np.array([0.25] * 4),
                     "m_q": (mu * share) * m_scale,
                     "q4_enter_margin": 0.0})
    return pd.DataFrame(rows)


def test_evaluate_arms_perfect_m_passes_and_copy_of_b0_fails():
    df = _eval_df(1.0)
    # M identical to B0 cannot pass: leg 1 is a strict inequality.
    ev = m.evaluate_arms(df.assign(m_q=df["b0_q"]))
    assert ev["screen_pass"] is False
    assert ev["legs"]["L1_pooled_beats_b0_and_b1"] is False
    # A near-perfect M passes all four legs.
    df2 = _eval_df(1.0)
    df2["m_q"] = df2["real_q"]
    ev2 = m.evaluate_arms(df2)
    assert ev2["screen_pass"] is True
    assert ev2["legs"]["L2_buckets_beating_b0"]["wins"] == 6
    assert ev2["legs"]["L3_q4_beats_b0"] is True
    assert ev2["legs"]["L4_stability"]["pass"] is True


def test_panel_integrity_counts():
    panel = pd.DataFrame([
        {"game_id": "x1", "team": "AAA", "q1": 7, "q2": 3, "q3": 0,
         "q4": 7},
        {"game_id": "x1", "team": "BBB", "q1": 0, "q2": 7, "q3": 3,
         "q4": 3},
        {"game_id": "x2", "team": "AAA", "q1": 7, "q2": 0, "q3": 0,
         "q4": 0},
        {"game_id": "x2", "team": "BBB", "q1": 3, "q2": 3, "q3": 0,
         "q4": 0},
    ])
    games = pd.DataFrame([
        {"game_id": "x1", "game_type": "REG", "home_team": "AAA",
         "away_team": "BBB", "home_score": 17.0, "away_score": 13.0,
         "overtime": 0},
        {"game_id": "x2", "game_type": "REG", "home_team": "AAA",
         "away_team": "BBB", "home_score": 10.0, "away_score": 6.0,
         "overtime": 1},
    ])
    out = m.panel_integrity(panel, games)
    assert out["n_team_games"] == 4
    assert out["exact_share"] == pytest.approx(0.75)
    assert out["ot_only_share"] == pytest.approx(0.25)
    assert out["negative_diffs"] == 0 and out["nan_rows"] == 0
