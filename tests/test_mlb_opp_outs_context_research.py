"""Context lane 2a research (#1482 D2a): opponent profile -> pitcher outs math, parity, intake hook."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_opp_outs_context_research as R
from sportsedge.mlb_opp_k_context_research import production_window
from sportsedge.mlb_pitcher_prior_research import OUTS_THRESH

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gamelog_parses_outs_opponent_and_skips_relief():
    payload = {"stats": [{"splits": [
        {"date": "2025-04-01", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 1}, "stat": {"gamesStarted": 1, "inningsPitched": "5.2"}},
        {"date": "2025-04-03", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 2}, "stat": {"gamesStarted": 0, "inningsPitched": "1.0"}},
        {"date": "2025-04-05", "team": {"id": 145}, "game": {"gamePk": 3}, "stat": {"gamesStarted": 1, "inningsPitched": "6.0"}},
        {"date": "2025-04-07", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 4}, "stat": {"gamesStarted": 1, "inningsPitched": "6.4"}},
    ]}]}
    rows = R.ostarts_from_gamelog(payload, pitcher_id=7, season=2025)
    assert [(r.outs, r.opp_id, r.game_pk) for r in rows] == [(17, 114, 1)]


def test_team_gamelog_builds_both_indices():
    payload = {"stats": [{"splits": [
        {"date": "2025-04-02", "stat": {"strikeOuts": 9, "hits": 8, "baseOnBalls": 3, "hitByPitch": 1, "plateAppearances": 38}},
        {"date": "2025-04-01", "stat": {"strikeOuts": 7, "hits": 10, "baseOnBalls": 2, "plateAppearances": 35}},
        {"date": "2025-04-03", "stat": {"strikeOuts": 4, "hits": 30, "baseOnBalls": 5, "hitByPitch": 0, "plateAppearances": 30}},  # invalid
    ]}]}
    rows = R.team_rows_from_gamelog(payload)
    assert rows["kidx"] == [("2025-04-01", 7, 35), ("2025-04-02", 9, 38)]
    assert rows["obidx"] == [("2025-04-01", 12, 35), ("2025-04-02", 12, 38)]


def _teams():
    # Team 1: high K, low on-base. Team 2: low K, high on-base. Same in both seasons.
    out = {}
    for season in (2024, 2025):
        d = f"{season}-04-01"
        out[(1, season)] = {"kidx": [(d, 30, 100)], "obidx": [(d, 25, 100)]}
        out[(2, season)] = {"kidx": [(d, 15, 100)], "obidx": [(d, 35, 100)]}
    return R.build_indices(out)


def test_indices_are_built_per_event():
    idx = _teams()
    assert idx["kidx"].z_prev(1, 2025) == pytest.approx(30 / 22.5)
    assert idx["obidx"].z_prev(1, 2025) == pytest.approx(25 / 30)


def test_baseline_matches_production_engine():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    pool = [{"strikeouts": k, "outs": o, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1}
            for k, o in [(3, 12), (5, 15), (7, 18), (6, 17), (4, 16), (8, 19)]]
    own = [R.OStart(1, 2025, f"2025-04-0{i}", i, 10, 2, r["outs"]) for i, r in enumerate(pool, 1)]
    target = R.OStart(1, 2025, "2025-04-20", 99, 10, 1, 0)
    pred = R.predict_outs(own, target, _teams(), R.BASELINE)
    for line in (14.5, 15.5, 16.5, 17.5):
        for side in ("OVER", "UNDER"):
            eng = price_pitcher_market({"market": "PITCHER_OUTS", "side": side, "line": line, "features": {"history_pool": pool}})
            i = int(np.where(np.isclose(OUTS_THRESH, line))[0][0])
            want = pred[i] if side == "OVER" else 1 - pred[i]
            assert want == pytest.approx(eng["model_p"], abs=1e-12)


def test_adjustment_direction_and_mass_preservation():
    idx = _teams()
    own = [R.OStart(1, 2025, f"2025-04-0{i}", i, 10, 2, o) for i, o in enumerate([15, 16, 17, 16, 15], 1)]
    vs_high_k = R.OStart(1, 2025, "2025-04-20", 99, 10, 1, 0)  # tonight's opponent strikes out more than past ones
    base = R.predict_outs(own, vs_high_k, idx, R.BASELINE)
    down = R.predict_outs(own, vs_high_k, idx, ("kidx", -1.0))
    up = R.predict_outs(own, vs_high_k, idx, ("kidx", 1.0))
    i = int(np.where(np.isclose(OUTS_THRESH, 15.5))[0][0])
    assert down[i] < base[i] < up[i]
    # On-base index is lower for team 1, so a negative beta raises outs.
    assert R.predict_outs(own, vs_high_k, idx, ("obidx", -1.0))[i] > base[i]
    m = R.adjusted_outs_mass_over([15.0, 16.0, 17.4])
    assert m.sum() == pytest.approx((15 + 16 + 17.4) / 3)
    assert R.adjusted_outs_mass_over([40.0])[-1] == pytest.approx(1.0)
    assert R.factor(own, vs_high_k, idx["kidx"], 1.0) == pytest.approx(2.0)


def test_select_prefers_baseline_on_ties_and_ship_rules():
    table = {c: 1.0 for c in R.CANDIDATES}
    assert R.select(table) == R.BASELINE
    table[("obidx", -0.5)] = 0.9
    assert R.select(table) == ("obidx", -0.5)

    idx = _teams()
    rows = []
    for pid in range(60):
        for g in range(8):
            opp = 1 if (pid + g) % 2 else 2
            mu = 13.0 if opp == 1 else 18.0  # high-K opponent truly shortens starts
            y = int(min(27, np.random.default_rng(pid * 100 + g).poisson(mu)))
            own = [R.OStart(pid, 2025, f"2025-04-0{i}", i, 10, 2 if i % 2 else 1,
                            int(min(27, np.random.default_rng(pid * 1000 + g * 10 + i).poisson(18.0 if i % 2 else 13.0))))
                   for i in range(1, 8)]
            tgt = R.OStart(pid, 2025, "2025-04-20", g, 10, opp, y)
            rows.append({"pitcher_id": pid, "y_outs": y, "rel": {n: idx[n].rel(opp, 2025, tgt.date) for n in idx},
                         "preds": {c: R.predict_outs(own, tgt, idx, c) for c in R.CANDIDATES}})
    cand = R.select(R.rps_table(rows))
    assert cand != R.BASELINE
    dec = R.ship_decision(rows, cand)
    assert dec["rule1_not_baseline"] and dec["bootstrap_vs_base"]["diff"] < 0
    assert R.ship_decision(rows, R.BASELINE)["ships"] is False


def test_runner_end_to_end_on_synthetic_logs(tmp_path):
    runner = _load("oppouts_runner", "scripts/research_mlb_opp_outs_context.py")
    starts, teams = [], {}
    for season in (2022, 2023, 2024, 2025):
        for t in (1, 2):
            days = [f"{season}-0{m}-{d:02d}" for m in (4, 5, 6) for d in range(1, 29)]
            teams[(t, season)] = {"kidx": [(d, 25 if t == 1 else 15, 100) for d in days],
                                  "obidx": [(d, 28 if t == 1 else 34, 100) for d in days]}
    for season in (2023, 2024, 2025):
        for pid in range(20):
            for g in range(12):
                opp = 1 if (pid + g) % 2 else 2
                o = int(min(27, np.random.default_rng(season * 10000 + pid * 100 + g).poisson(14.0 if opp == 1 else 17.0)))
                starts.append(R.OStart(pid, season, f"{season}-0{4 + g // 5}-{(g % 5) * 5 + 2:02d}", season * 1000 + pid * 20 + g, 10, opp, o))
    assert len(production_window(starts)) == len(starts)
    result, md = runner.run(starts, teams)
    assert "held-out validation" in md and "no picks changed" in md
    assert result["tune"]["units"] > 0 and result["test"]["units"] > 0
    assert len(result["test"]["rps"]) == len(R.CANDIDATES) == 17


def test_intake_registers_directive():
    intake = _load("intake_oppouts", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH opp_outs_context") == "opp_outs_context"
    assert intake.RESEARCH_DIRECTIVES["opp_outs_context"] == ["scripts/research_mlb_opp_outs_context.py"]
    assert (ROOT / intake.RESEARCH_DIRECTIVES["opp_outs_context"][0]).exists()
