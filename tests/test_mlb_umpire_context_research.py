"""Context lane 2b research (#1482 D2b): umpire -> pitcher K / BB math, parity, intake hook."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_umpire_context_research as R
from sportsedge.mlb_opp_k_context_research import OppIndex, production_window

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_parsers():
    p = {"stats": [{"splits": [
        {"date": "2025-04-01", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 11}, "stat": {"gamesStarted": 1, "strikeOuts": 6, "baseOnBalls": 2}},
        {"date": "2025-04-03", "team": {"id": 145}, "opponent": {"id": 114}, "game": {"gamePk": 12}, "stat": {"gamesStarted": 0, "strikeOuts": 1, "baseOnBalls": 0}},
        {"date": "2025-04-05", "team": {"id": 145}, "opponent": {"id": 114}, "stat": {"gamesStarted": 1, "strikeOuts": 5}},
    ]}]}
    rows = R.ustarts_from_gamelog(p, pitcher_id=7, season=2025)
    assert [(r.k, r.bb, r.opp_id, r.game_pk) for r in rows] == [(6, 2, 114, 11)]

    t = {"stats": [{"splits": [
        {"date": "2025-04-01", "game": {"gamePk": 11}, "stat": {"strikeOuts": 9, "baseOnBalls": 3, "plateAppearances": 38}},
        {"date": "2025-04-02", "stat": {"strikeOuts": 9, "baseOnBalls": 3, "plateAppearances": 38}},
    ]}]}
    assert R.team_game_rows(t) == [(11, "2025-04-01", 9, 3, 38)]

    sched = {"dates": [{"games": [
        {"gamePk": 11, "officials": [{"officialType": "First Base", "official": {"id": 1}}, {"officialType": "Home Plate", "official": {"id": 99}}]},
        {"gamePk": 12, "officials": []},
    ]}]}
    assert R.home_plate_by_game(sched) == {11: 99}


def test_game_totals_need_both_teams():
    rows = [(1, "2025-04-01", 8, 3, 38), (1, "2025-04-01", 10, 2, 40), (2, "2025-04-01", 5, 1, 30)]
    assert R.game_totals(rows) == {1: ("2025-04-01", 18, 5, 78)}


def _ump_index():
    # Umpire 1 calls 25% K / 5% BB games, umpire 2 15% / 12%; each works 30 games in 2024.
    games, umps = {}, {}
    for i in range(60):
        d = f"2024-{4 + i // 20:02d}-{(i % 20) + 1:02d}"
        u = 1 if i % 2 else 2
        games[i + 1] = (d, 20 if u == 1 else 12, 4 if u == 1 else 10, 80)
        umps[i + 1] = u
    return R.UmpIndex(games, umps), umps


def test_index_is_strictly_prior_shrunk_and_neutral_when_unknown():
    idx, _ = _ump_index()
    d = "2025-03-01"
    league = (30 * 20 + 30 * 12) / 4800
    want = (30 * 20 + 2000 * league) / ((2400 + 2000) * league)
    assert idx.rel(1, d, "k", 2000.0) == pytest.approx(want)
    assert idx.rel(1, d, "k", 6000.0) < want  # more shrinkage
    assert idx.rel(2, d, "bb", 2000.0) > 1.0
    assert idx.rel(None, d, "k", 2000.0) == 1.0 and idx.rel(42, d, "k", 2000.0) == 1.0
    assert idx.rel(1, "2024-04-01", "k", 2000.0) == 1.0  # no prior games
    assert idx.rel(1, "2026-04-01", "k", 2000.0) == 1.0  # outside 365-day window


def _opp():
    rows = {}
    for season in (2024, 2025):
        rows[(1, season)] = [(f"{season}-04-01", 30, 100)]
        rows[(2, season)] = [(f"{season}-04-01", 15, 100)]
    return OppIndex(rows)


def _pool():
    return [{"strikeouts": k, "outs": o, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": bb}
            for k, o, bb in [(3, 12, 1), (5, 15, 3), (7, 18, 0), (6, 17, 2), (4, 16, 4), (8, 19, 1)]]


def test_bb_baseline_matches_production_engine():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    idx, umps = _ump_index()
    pool = _pool()
    own = [R.UStart(1, 2025, f"2025-04-0{i}", 1000 + i, 10, 2, r["strikeouts"], r["walks_allowed"]) for i, r in enumerate(pool, 1)]
    target = R.UStart(1, 2025, "2025-04-20", 2000, 10, 1, 0, 0)
    pred = R.predict("bb", own, target, umps, idx, None, R.BASELINE)
    for line in (0.5, 1.5, 2.5, 3.5):
        for side in ("OVER", "UNDER"):
            eng = price_pitcher_market({"market": "PITCHER_BB", "side": side, "line": line, "features": {"history_pool": pool}})
            i = int(np.where(np.isclose(R.THRESH["bb"], line))[0][0])
            assert (pred[i] if side == "OVER" else 1 - pred[i]) == pytest.approx(eng["model_p"], abs=1e-12)


def test_k_baseline_matches_production_opp_k_engine():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    idx, umps = _ump_index()
    opp = _opp()
    pool = _pool()
    own = [R.UStart(1, 2025, f"2025-04-0{i + 1}", 1000 + i, 10, 2 if i % 2 else 1, r["strikeouts"], r["walks_allowed"]) for i, r in enumerate(pool)]
    target = R.UStart(1, 2025, "2025-04-20", 2000, 10, 1, 0, 0)
    pred = R.predict("k", own, target, umps, idx, opp, R.BASELINE)
    adj = {"market": "PITCHER_K", "beta": 1.0, "target_rel": opp.rel(1, 2025, target.date),
           "history_rel": [opp.rel(r.opp_id, r.season, r.date) for r in own]}
    for line in np.arange(0, 20) + 0.5:
        for side in ("OVER", "UNDER"):
            eng = price_pitcher_market({"market": "PITCHER_K", "side": side, "line": float(line),
                                        "features": {"history_pool": pool, "opp_k_adjustment": adj}})
            i = int(np.where(np.isclose(R.THRESH["k"], line))[0][0])
            assert (pred[i] if side == "OVER" else 1 - pred[i]) == pytest.approx(eng["model_p"], abs=1e-12)


def test_adjustment_direction():
    idx, umps = _ump_index()
    umps = dict(umps)
    own = [R.UStart(1, 2025, f"2025-04-0{i}", 500 + i, 10, 2, 5, 2) for i in range(1, 7)]
    for s in own:
        umps[s.game_pk] = 2  # history under the low-K / high-BB umpire
    target = R.UStart(1, 2025, "2025-04-20", 900, 10, 2, 0, 0)
    umps[900] = 1  # tonight: high-K / low-BB umpire
    i_k = int(np.where(np.isclose(R.THRESH["k"], 5.5))[0][0])
    i_bb = int(np.where(np.isclose(R.THRESH["bb"], 1.5))[0][0])
    opp = _opp()
    assert R.predict("k", own, target, umps, idx, opp, (2000.0, 1.0))[i_k] > R.predict("k", own, target, umps, idx, opp, R.BASELINE)[i_k]
    assert R.predict("bb", own, target, umps, idx, None, (2000.0, 1.0))[i_bb] < R.predict("bb", own, target, umps, idx, None, R.BASELINE)[i_bb]
    m = R.adjusted_mass_over([1.0, 2.0, 2.4], "bb")
    assert m.sum() == pytest.approx((1 + 2 + 2.4) / 3)
    assert R.adjusted_mass_over([40.0], "bb")[-1] == pytest.approx(1.0)


def test_select_ties_and_ship_rules():
    table = {c: 1.0 for c in R.CANDIDATES}
    assert R.select(table) == R.BASELINE
    table[(6000.0, 1.5)] = 0.9
    assert R.select(table) == (6000.0, 1.5)
    assert len(R.CANDIDATES) == 9


def _synthetic():
    """Two umpires with a real K / BB effect; four seasons of games and starts."""
    rng = np.random.default_rng(7)
    teams, umps, starts = {}, {}, []
    pk = 0
    for season in (2022, 2023, 2024, 2025):
        for t in (1, 2):
            teams[(t, season)] = []
        for day in range(1, 120):
            d = (np.datetime64(f"{season}-04-01") + np.timedelta64(day, "D")).astype(str)
            pk += 1
            u = 1 + (day % 2)
            umps[pk] = u
            kr, br = (0.27, 0.06) if u == 1 else (0.17, 0.11)
            for t in (1, 2):
                teams[(t, season)].append((pk, d, int(rng.binomial(38, kr)), int(rng.binomial(38, br)), 38))
            if season >= 2023:
                for pid in range(8):
                    if (day + pid) % 5 == 0:
                        lam_k, lam_b = (7.0, 1.5) if u == 1 else (4.0, 3.0)
                        starts.append(R.UStart(pid, season, d, pk, 1, 2, int(rng.poisson(lam_k)), int(rng.poisson(lam_b))))
    return starts, teams, umps


def test_runner_end_to_end_on_synthetic_logs():
    runner = _load("ump_runner", "scripts/research_mlb_umpire_context.py")
    starts, teams, umps = _synthetic()
    assert len(production_window(starts)) == len(starts)
    result, md = runner.run(starts, teams, umps)
    assert "held-out validation" in md and "no picks changed" in md
    for stat in ("k", "bb"):
        lane = result["lanes"][stat]
        assert lane["tune_units"] > 0 and lane["test_units"] > 0
        assert len(lane["test_rps"]) == 9
        # The synthetic umpire effect is strong, so the lane should be selected and help.
        assert lane["selected"] != "baseline (production)"
        assert lane["decision"]["bootstrap_vs_base"]["diff"] < 0


def test_runner_refuses_incomplete_officials():
    runner = _load("ump_runner2", "scripts/research_mlb_umpire_context.py")
    starts, teams, umps = _synthetic()
    sparse = {k: v for i, (k, v) in enumerate(umps.items()) if i % 3 == 0}
    with pytest.raises(RuntimeError, match="home-plate umpire"):
        runner.run(starts, teams, sparse)


def test_intake_registers_directive():
    intake = _load("intake_ump", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH umpire_context") == "umpire_context"
    assert intake.RESEARCH_DIRECTIVES["umpire_context"] == ["scripts/research_mlb_umpire_context.py"]
    assert (ROOT / intake.RESEARCH_DIRECTIVES["umpire_context"][0]).exists()
