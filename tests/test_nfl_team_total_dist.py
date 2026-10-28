"""Tests for NFL_TEAM_TOTAL_DIST_V1 (sportsedge/nfl_team_total_dist.py).

The construction is the one designed and screened in
research/nfl_activation_20261027 (DESIGN_NFL_TEAM_TOTALS_V1): shrunk
offensive x defensive team means over a negative-binomial law, zero
market input. These tests pin the point-in-time discipline (a game
must not see its own or later data), the shrinkage form, the sample
rules, and the distribution law.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from sportsedge import nfl_team_total_dist as eng
from sportsedge.forward_validation.core import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def G(season, week, gameday, gid, home, away, hs, as_, gtype="REG"):
    return eng.GameRecord(season=season, week=week, gameday=gameday,
                          game_id=gid, home_team=home, away_team=away,
                          home_score=hs, away_score=as_, game_type=gtype)


# ---------------------------------------------------------------------------
# Exact arithmetic on a two-team toy league (hand-computed expectations)
# ---------------------------------------------------------------------------

def _toy_history():
    # 2024: A 30-10 B (wk1); B 20-24 A (wk2, B home). Full-season league
    # mean = (30+10+20+24)/4 = 21.0.
    return [
        G(2024, 1, "2024-09-05", "2024_01_B_A", "A", "B", 30, 10),
        G(2024, 2, "2024-09-12", "2024_02_A_B", "B", "A", 20, 24),
    ]


def test_week1_prediction_uses_prior_season_league_mean_and_shrinkage():
    engine = eng.TeamTotalDistEngine()
    engine.process_snapshot(_toy_history())
    game = G(2025, 1, "2025-09-04", "2025_01_B_A", "A", "B", None, None)
    home, away = engine.predict_game(game)
    # G = prior season's full league mean.
    assert home.league_mean == pytest.approx(21.0)
    # A's sample = both 2024 games (supplement): scores-for [30, 24].
    assert home.off_sample_n == 2
    assert home.b1_team_mean == pytest.approx(27.0)
    # off_A = (54 + 3*21) / (2 + 3) = 23.4; def_B on allowed [30, 24] = 23.4.
    assert home.off_rate == pytest.approx(23.4)
    assert home.def_rate == pytest.approx(23.4)
    assert home.mu == pytest.approx(23.4 * 23.4 / 21.0)
    # B: off from [10, 20] = 18.6; def from A allowed [10, 20] = 18.6.
    assert away.mu == pytest.approx(18.6 * 18.6 / 21.0)
    assert home.b2_league_mean == pytest.approx(21.0)


def test_empty_history_shrinks_fully_to_league_mean():
    engine = eng.TeamTotalDistEngine()
    pred = engine.predict_team("NEW", "OPP", 2025, 1)
    assert pred.league_mean == pytest.approx(eng.DEFAULT_LEAGUE_MEAN)
    assert pred.off_rate == pytest.approx(pred.league_mean)
    assert pred.def_rate == pytest.approx(pred.league_mean)
    assert pred.mu == pytest.approx(pred.league_mean)
    assert pred.b1_team_mean == pytest.approx(pred.league_mean)


def test_shrunk_mean_form_and_monotone_approach():
    shrunk = eng.TeamTotalDistEngine._shrunk_mean
    assert shrunk([40.0], 20.0) == pytest.approx((40.0 + 3 * 20.0) / 4.0)
    one = shrunk([40.0], 20.0)
    eight = shrunk([40.0] * 8, 20.0)
    assert 20.0 < one < eight < 40.0  # approaches the sample mean in n


def test_sample_cap_last_eight_same_season():
    games = []
    for wk in range(1, 11):  # A scores 10+wk, B scores 7 every week
        games.append(G(2025, wk, f"2025-09-{wk:02d}", f"g{wk:02d}",
                       "A", "B", 10 + wk, 7))
    engine = eng.TeamTotalDistEngine()
    engine.process_snapshot(games)
    pred = engine.predict_team("A", "B", 2025, 11)
    assert pred.off_sample_n == 8
    last8 = [10 + wk for wk in range(3, 11)]  # weeks 3..10
    assert pred.b1_team_mean == pytest.approx(float(np.mean(last8)))


def test_sample_supplement_prior_season_most_recent_first():
    games = []
    for wk in range(1, 7):  # 2024: A scores 20+wk (21..26), B scores 9
        games.append(G(2024, wk, f"2024-09-{wk:02d}", f"p{wk:02d}",
                       "A", "B", 20 + wk, 9))
    for wk in range(1, 4):  # 2025: A scores 30+wk (31..33), B scores 9
        games.append(G(2025, wk, f"2025-09-{wk:02d}", f"c{wk:02d}",
                       "A", "B", 30 + wk, 9))
    engine = eng.TeamTotalDistEngine()
    engine.process_snapshot(games)
    pred = engine.predict_team("A", "B", 2025, 4)
    # Sample = last 5 of 2024 (22..26) + all 3 of 2025 (31..33) = 8 games.
    expect = [22, 23, 24, 25, 26, 31, 32, 33]
    assert pred.off_sample_n == 8
    assert pred.b1_team_mean == pytest.approx(float(np.mean(expect)))


# ---------------------------------------------------------------------------
# Point-in-time leakage probes
# ---------------------------------------------------------------------------

def _season_games():
    games = []
    scores = [(24, 17), (31, 28), (20, 20), (27, 10), (13, 30), (35, 21)]
    for i, (hs, as_) in enumerate(scores, start=1):
        games.append(G(2025, i, f"2025-09-{i:02d}", f"s{i:02d}",
                       "A", "B", hs, as_))
    return games


def test_own_game_score_cannot_enter_own_prediction():
    games = _season_games()
    target = 3  # index of the 4th game
    engine1 = eng.TeamTotalDistEngine()
    preds1 = engine1.process_snapshot(games)
    altered = list(games)
    g = altered[target]
    altered[target] = G(g.season, g.week, g.gameday, g.game_id,
                        g.home_team, g.away_team, 99, 0)
    engine2 = eng.TeamTotalDistEngine()
    preds2 = engine2.process_snapshot(altered)
    assert preds1[target][1].mu == preds2[target][1].mu
    assert preds1[target][2].mu == preds2[target][2].mu


def test_future_games_cannot_enter_prediction():
    games = _season_games()
    engine_full = eng.TeamTotalDistEngine()
    preds_full = engine_full.process_snapshot(games)
    target = 2
    engine_trunc = eng.TeamTotalDistEngine()
    engine_trunc.process_snapshot(games[:target])
    home, away = engine_trunc.predict_game(games[target])
    assert home.mu == preds_full[target][1].mu
    assert away.mu == preds_full[target][2].mu


def test_prediction_does_not_mutate_state():
    engine = eng.TeamTotalDistEngine()
    engine.process_snapshot(_season_games())
    game = G(2025, 7, "2025-10-20", "s07", "A", "B", None, None)
    first = engine.predict_game(game)
    second = engine.predict_game(game)
    assert first[0].mu == second[0].mu and first[1].mu == second[1].mu


def test_record_game_refuses_nonfinal_and_nonregular():
    engine = eng.TeamTotalDistEngine()
    with pytest.raises(ValueError):
        engine.record_game(G(2025, 1, "2025-09-04", "x1", "A", "B",
                             None, None))
    with pytest.raises(ValueError):
        engine.record_game(G(2025, 20, "2026-01-10", "x2", "A", "B",
                             24, 17, gtype="POST"))


def test_deterministic_repeated_runs():
    games = _season_games()
    mus1 = [p.mu for _, h, a in eng.TeamTotalDistEngine()
            .process_snapshot(games) for p in (h, a)]
    mus2 = [p.mu for _, h, a in eng.TeamTotalDistEngine()
            .process_snapshot(games) for p in (h, a)]
    assert mus1 == mus2


def test_engine_has_no_market_inputs():
    fields = {f.name for f in dataclasses.fields(eng.GameRecord)}
    assert not fields & {"spread", "total", "spread_line", "total_line",
                         "line", "price", "odds"}
    params = set(inspect.signature(eng.TeamTotalDistEngine
                                   .predict_team).parameters)
    assert not params & {"spread", "total", "line", "price", "odds"}


# ---------------------------------------------------------------------------
# Distribution law sanity
# ---------------------------------------------------------------------------

def test_nb_law_moments_and_support():
    mu, c = 24.0, eng.POOLED_CV_C
    pmf = eng.nb_pmf_grid(mu, c)
    cdf = eng.nb_cdf_grid(mu, c)
    assert pmf.shape == (eng.MAX_SCORE + 1,)
    assert np.all(np.diff(cdf) >= 0)  # monotone CDF
    assert cdf[-1] == pytest.approx(1.0, abs=1e-6)
    assert pmf.sum() == pytest.approx(1.0, abs=1e-6)
    ks = np.arange(0, eng.MAX_SCORE + 1)
    mean = float(np.sum(ks * pmf))
    var = float(np.sum(((ks - mean) ** 2) * pmf))
    assert mean == pytest.approx(mu, abs=0.05)
    assert var == pytest.approx((c * mu) ** 2, rel=0.03)


def test_poisson_branch_for_small_mu():
    mu = 0.5  # (c*mu)^2 = 0.054 <= mu -> Poisson branch
    ks = np.arange(0, eng.MAX_SCORE + 1)
    assert np.allclose(eng.nb_cdf_grid(mu), stats.poisson.cdf(ks, mu))


def test_probabilities_partition():
    mu = 23.4
    over = eng.prob_over(mu, 24.5)
    under = eng.prob_under(mu, 24.5)
    assert over + under == pytest.approx(1.0)
    assert eng.prob_push(mu, 24.5) == 0.0
    o2 = eng.prob_over(mu, 24)
    u2 = eng.prob_under(mu, 24)
    p2 = eng.prob_push(mu, 24)
    assert o2 + u2 + p2 == pytest.approx(1.0)
    assert p2 == pytest.approx(float(eng.nb_pmf_grid(mu)[24]))


def test_crps_zero_for_degenerate_realized_at_mode_mass():
    cdf = eng.nb_cdf_grid(20.0)
    value = eng.crps_from_cdf(cdf, 20)
    assert 0.0 < value < 6.0  # sane scale for an NFL team total


# ---------------------------------------------------------------------------
# Training constant derivation (hand-computed on a two-game training season)
# ---------------------------------------------------------------------------

def test_derive_pooled_cv_hand_computed():
    games = [
        G(2019, 1, "2019-09-05", "t1", "A", "B", 28, 14),
        G(2019, 2, "2019-09-12", "t2", "B", "A", 21, 17),
    ]
    # Hand derivation. Game 1 (empty state): G = 22.0, both mus = 22.0.
    # After game 1: in-season scores [28, 14] -> G = 21.0 for game 2.
    # Game 2 home B: off_B = (14 + 3*21)/4 = 19.25; def vs A allowed
    # [14] -> (14 + 63)/4 = 19.25; mu_B = 19.25^2 / 21.
    # Game 2 away A: off_A = (28 + 63)/4 = 22.75; def vs B allowed [28]
    # -> 22.75; mu_A = 22.75^2 / 21.
    mu_b2 = 19.25 * 19.25 / 21.0
    mu_a2 = 22.75 * 22.75 / 21.0
    ratios = np.array([28 / 22.0, 14 / 22.0, 21 / mu_b2, 17 / mu_a2])
    expected = float(np.std(ratios, ddof=0))
    got = eng.derive_pooled_cv(games)
    assert got == pytest.approx(expected, rel=1e-12)
    assert math.isfinite(got) and got > 0


# ---------------------------------------------------------------------------
# Framework config <-> engine pin binding
# ---------------------------------------------------------------------------

def test_config_loads_and_pin_matches_engine_file():
    cfg_path = (REPO_ROOT / "sportsedge" / "forward_validation"
                / "configs" / "nfl_team_total.json")
    cfg = load_config(cfg_path)
    assert cfg.sport == "NFL" and cfg.family == "TEAM_TOTAL"
    assert cfg.engine_id == eng.ENGINE_ID
    # Freeze act: the config froze with the preregistration; the freeze
    # takes effect only at the freeze-act merge (see FREEZE_RECORD.md).
    assert cfg.status.startswith("FROZEN")
    assert cfg.prereg_sha256 == hashlib.sha256(
        (REPO_ROOT / cfg.prereg).read_bytes()).hexdigest()
    assert cfg.min_rows == 150 and cfg.min_events == 40
    assert cfg.min_slates == 4
    engine_sha = hashlib.sha256(
        (REPO_ROOT / "sportsedge" / "nfl_team_total_dist.py")
        .read_bytes()).hexdigest()
    # The config's model_version is the pinnable pin string: any change
    # to the engine file breaks this test until the pin is re-struck.
    assert cfg.model_version == f"{eng.MODEL_VERSION}@sha256:{engine_sha}"
