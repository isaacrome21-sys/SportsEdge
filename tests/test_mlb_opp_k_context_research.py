"""Context lane 1 research (#1482 D): opponent-K adjustment math, parity, and intake hook."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_opp_k_context_research as O
from sportsedge.mlb_pitcher_prior_research import K_THRESH

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gamelog_parses_opponent_and_skips_relief():
    payload = {"stats": [{"splits": [
        {"date": "2025-04-01", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 1}, "stat": {"gamesStarted": 1, "strikeOuts": 6}},
        {"date": "2025-04-03", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 2}, "stat": {"gamesStarted": 0, "strikeOuts": 2}},
        {"date": "2025-04-05", "team": {"id": 145}, "game": {"gamePk": 3}, "stat": {"gamesStarted": 1, "strikeOuts": 4}},
    ]}]}
    rows = O.kstarts_from_gamelog(payload, pitcher_id=7, season=2025)
    assert [(r.k, r.opp_id, r.game_pk) for r in rows] == [(6, 114, 1)]


def test_team_gamelog_parsing():
    payload = {"stats": [{"splits": [
        {"date": "2025-04-02", "stat": {"strikeOuts": 9, "plateAppearances": 38}},
        {"date": "2025-04-01", "stat": {"strikeOuts": 7, "plateAppearances": 35}},
        {"date": "2025-04-03", "stat": {"strikeOuts": 40, "plateAppearances": 30}},  # invalid
    ]}]}
    assert O.team_games_from_gamelog(payload) == [("2025-04-01", 7, 35), ("2025-04-02", 9, 38)]


def _index():
    # Team 1 strikes out twice as often as team 2 in both seasons.
    games = {
        (1, 2024): [("2024-06-01", 20, 100)], (2, 2024): [("2024-06-01", 10, 100)],
        (1, 2025): [("2025-04-01", 20, 100), ("2025-04-02", 20, 100)],
        (2, 2025): [("2025-04-01", 10, 100), ("2025-04-02", 10, 100)],
    }
    return O.OppIndex(games)


def test_opp_index_is_strictly_prior_and_shrunk():
    idx = _index()
    # League 2024 K/PA = 0.15; team 1 = 0.20 -> z_prev = 4/3.
    assert idx.z_prev(1, 2025) == pytest.approx(4 / 3)
    # Before any 2025 game: prior only.
    assert idx.rel(1, 2025, "2025-04-01") == pytest.approx(4 / 3)
    # Same-day game excluded; after day 1: 100 PA current (z=4/3) + 1000 PA prior (4/3).
    assert idx.rel(1, 2025, "2025-04-02") == pytest.approx(4 / 3)
    # Unknown team/season falls back to neutral.
    assert idx.rel(99, 2025, "2025-04-02") == pytest.approx(1.0)


def test_opp_index_blend_weights():
    games = {(1, 2024): [("2024-06-01", 15, 100)], (2, 2024): [("2024-06-01", 15, 100)],
             (1, 2025): [("2025-04-01", 30, 100)], (2, 2025): [("2025-04-01", 10, 100)]}
    idx = O.OppIndex(games)
    # z_prev = 1; z_cur = 0.30 / 0.20 = 1.5; rel = (100*1.5 + 1000*1) / 1100
    assert idx.rel(1, 2025, "2025-04-02") == pytest.approx((150 + 1000) / 1100)


def test_beta_zero_matches_production_engine():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    pool = [{"strikeouts": k, "outs": o, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1}
            for k, o in [(3, 12), (5, 15), (7, 18), (6, 17), (4, 16), (8, 19)]]
    own = [O.KStart(1, 2025, f"2025-04-0{i}", i, 10, 2, r["strikeouts"]) for i, r in enumerate(pool, 1)]
    target = O.KStart(1, 2025, "2025-04-20", 99, 10, 1, 0)
    pred = O.predict_k(own, target, _index(), 0.0)
    for line in (3.5, 4.5, 5.5, 6.5):
        eng = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": line, "features": {"history_pool": pool}})
        i = int(np.where(np.isclose(K_THRESH, line))[0][0])
        assert pred[i] == pytest.approx(eng["model_p"], abs=1e-12)


def test_adjustment_direction_and_mass_preservation():
    idx = _index()
    own = [O.KStart(1, 2025, f"2025-04-0{i}", i, 10, 2, k) for i, k in enumerate([4, 5, 6, 5, 4], 1)]
    vs_high = O.KStart(1, 2025, "2025-04-20", 99, 10, 1, 0)  # opponent strikes out more than past opponents
    base = O.predict_k(own, vs_high, idx, 0.0)
    adj = O.predict_k(own, vs_high, idx, 1.0)
    assert np.all(adj >= base - 1e-12) and adj[4] > base[4]  # P(over 4.5) rises
    # Linear split preserves the mean: E[X] = sum of P(X > t) over integer t.
    m = O.adjusted_mass_over([4.0, 5.0, 6.3])
    assert m.sum() == pytest.approx((4 + 5 + 6.3) / 3)
    assert O.adjusted_mass_over([25.0])[-1] == pytest.approx(1.0)


def test_select_and_ship_rules_on_synthetic_data():
    idx = _index()
    rows = []
    for pid in range(60):
        for g in range(8):
            opp = 1 if (pid + g) % 2 else 2
            mu = 6.0 if opp == 1 else 3.0  # true effect of opponent
            y = int(np.random.default_rng(pid * 100 + g).poisson(mu))
            own = [O.KStart(pid, 2025, f"2025-04-0{i}", i, 10, 2 if i % 2 else 1,
                            int(np.random.default_rng(pid * 1000 + g * 10 + i).poisson(3.0 if i % 2 else 6.0)))
                   for i in range(1, 8)]
            tgt = O.KStart(pid, 2025, "2025-04-20", g, 10, opp, y)
            rows.append({"pitcher_id": pid, "y_k": y, "opp_rel": idx.rel(opp, 2025, tgt.date),
                         "preds": {b: O.predict_k(own, tgt, idx, b) for b in O.BETAS}})
    table = O.rps_table(rows)
    beta = O.select_beta(table)
    assert beta > 0
    dec = O.ship_decision(rows, beta)
    assert dec["rule1_beta_positive"] and dec["bootstrap_vs_base"]["diff"] < 0
    assert O.ship_decision(rows, 0.0)["ships"] is False


def test_runner_end_to_end_on_synthetic_logs(tmp_path):
    runner = _load("oppk_runner", "scripts/research_mlb_opp_k_context.py")
    starts, teams = [], {}
    for season in (2022, 2023, 2024, 2025):
        for t in (1, 2):
            teams[(t, season)] = [(f"{season}-0{m}-{d:02d}", (25 if t == 1 else 15), 100) for m in (4, 5, 6) for d in range(1, 29)]
    for season in (2023, 2024, 2025):
        for pid in range(20):
            for g in range(12):
                opp = 1 if (pid + g) % 2 else 2
                k = int(np.random.default_rng(season * 10000 + pid * 100 + g).poisson(6.0 if opp == 1 else 3.5))
                starts.append(O.KStart(pid, season, f"{season}-0{4 + g // 5}-{(g % 5) * 5 + 2:02d}", season * 1000 + pid * 20 + g, 10, opp, k))
    result, md = runner.run(starts, teams)
    assert "held-out validation" in md and "no picks changed" in md
    assert result["tune"]["units"] > 0 and result["test"]["units"] > 0
    assert set(result["test"]["rps"]) == set(O.BETAS)


def test_intake_registers_directive():
    intake = _load("intake_oppk", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH opp_k_context") == "opp_k_context"
    assert intake.RESEARCH_DIRECTIVES["opp_k_context"] == ["scripts/research_mlb_opp_k_context.py"]
    assert (ROOT / intake.RESEARCH_DIRECTIVES["opp_k_context"][0]).exists()
