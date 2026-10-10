"""Few-starts fallback BB/H/ER extension research (#1482): math, parity and intake hook."""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_pitcher_prior_ext_research as X
from sportsedge import mlb_pitcher_prior_research as R

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _s(pid, season, date, gpk, bb=1, h=4, er=2, outs=15, k=5, team=10):
    return X.XStart(pid, season, date, gpk, team, outs, k, bb, h, er)


def test_gamelog_parses_bb_h_er_and_keeps_only_starts():
    payload = {"stats": [{"splits": [
        {"date": "2025-04-01", "team": {"id": 145}, "game": {"gamePk": 1},
         "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 6, "baseOnBalls": 2, "hits": 5, "earnedRuns": 3}},
        {"date": "2025-04-03", "team": {"id": 145}, "game": {"gamePk": 2},
         "stat": {"gamesStarted": 0, "inningsPitched": "1.0", "strikeOuts": 2, "baseOnBalls": 0, "hits": 1, "earnedRuns": 0}},
    ]}]}
    rows = X.starts_from_gamelog(payload, pitcher_id=7, season=2025)
    assert [(r.outs, r.k, r.bb, r.h, r.er, r.team_id) for r in rows] == [(16, 6, 2, 5, 3, 145)]


def test_frozen_candidate_is_the_production_selection():
    assert (X.POOL, X.M) == ("league_short", 4.0)
    assert X.prereg_sha256() == __import__("hashlib").sha256(X.PREREG_PATH.read_bytes()).hexdigest()


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_fallback_formula_equals_production_engine_fallback(k):
    """Same arithmetic as pitcher_joint_engine._price_prior_fallback (checked via the PITCHER_K path)."""
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    rnd = random.Random(k)
    own_vals = [rnd.randint(0, 6) for _ in range(k)]
    prior_vals = [rnd.randint(0, 9) for _ in range(300)]
    counts: dict[str, int] = {}
    for v in prior_vals:
        counts[str(v)] = counts.get(str(v), 0) + 1
    own = [_s(1, 2025, f"2025-04-0{i + 1}", i + 1, bb=v) for i, v in enumerate(own_vals)]
    prior = {st: X._over_frac(prior_vals, st) for st in X.STATS}
    pred = X.predict_fallback(own, prior)["bb"]
    pool = [{"strikeouts": v, "outs": 15, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1} for v in own_vals]
    for i, line in enumerate(X.THRESH["bb"]):
        eng = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": float(line), "features": {
            "history_pool": pool, "prior_fallback": {"market": "PITCHER_K", "pseudo_starts": 4.0, "counts": counts, "pool": "league_short", "season": 2025}}})
        assert pred[i] == pytest.approx(eng["model_p"], abs=1e-12)


def test_own_only_matches_production_jeffreys_for_k_ge_5_bb():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    vals = [0, 1, 3, 2, 1, 4]
    pool = [{"strikeouts": 5, "outs": 15, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": v} for v in vals]
    own = [_s(1, 2025, f"2025-04-0{i + 1}", i + 1, bb=v) for i, v in enumerate(vals)]
    pred = X.predict_own(own)["bb"]
    for line in (0.5, 1.5, 2.5):
        eng = price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": line, "features": {"history_pool": pool}})
        i = int(np.where(np.isclose(X.THRESH["bb"], line))[0][0])
        assert pred[i] == pytest.approx(eng["model_p"], abs=1e-12)


def test_pool_uses_only_short_history_prior_season_starts():
    starts = [_s(1, 2023, f"2023-0{m}-01", m, bb=9) for m in range(4, 10)]  # 6 starts: last ones are k>=5
    starts += [_s(100 + i, 2023, "2023-05-01", 1000 + i, bb=0) for i in range(120)]  # debut starts, k=0
    window = R.prior_window_counts(starts)
    pool = X.league_short_pool(starts, window)
    # 120 debuts (bb=0) + pitcher 1's first five starts (k=0..4, bb=9); his 6th (k=5) is excluded.
    assert pool["bb"][0] == pytest.approx(5 / 125)


def test_evaluate_units_and_decision_on_synthetic_signal():
    rng = np.random.default_rng(0)
    starts = []
    gpk = 0
    for season in (2023, 2024, 2025):
        for pid in range(400):
            for j in range(rng.integers(1, 4)):  # mostly short histories
                gpk += 1
                starts.append(_s(pid + 1000 * season, season, f"{season}-0{4 + j}-01", gpk,
                                 bb=int(rng.poisson(2)), h=int(rng.poisson(5)), er=int(rng.poisson(2.5))))
    window = R.prior_window_counts(starts)
    by = {y: [s for s in starts if s.season == y] for y in (2023, 2024, 2025)}
    test = X.evaluate(by[2025], window, X.league_short_pool(by[2024], window), ks=range(1, 5))
    cons = X.evaluate(by[2024], window, X.league_short_pool(by[2023], window), ks=range(1, 5))
    assert test and all(1 <= r["k"] <= 4 and {"own", "fallback"} <= set(r["preds"]) for r in test)
    ref = X.evaluate(by[2025], window, X.league_short_pool(by[2024], window), ks=range(1, 5))  # stand-in reference
    for r in ref:
        r["preds"] = {"own": r["preds"]["own"]}
    d = X.ship_decision(test, cons, ref)
    # Homogeneous pitchers: shrinking 1-3 own starts toward the league pool must help every stat.
    for market in ("PITCHER_BB", "PITCHER_HITS_ALLOWED", "PITCHER_ER"):
        assert d["markets"][market]["test_vs_own"]["hi"] < 0
        assert d["markets"][market]["rule3_sign_2024"]


def test_intake_has_research_directive():
    intake = _load("mlb_intake_ext", "scripts/intake_mlb_lines_issue.py")
    assert intake.RESEARCH_DIRECTIVES["pitcher_prior_fallback_ext"] == ["scripts/research_mlb_pitcher_prior_fallback_ext.py"]
    assert intake.research_directive("RESEARCH pitcher_prior_fallback_ext") == "pitcher_prior_fallback_ext"


def test_runner_report_on_synthetic_starts():
    runner = _load("prior_ext_runner", "scripts/research_mlb_pitcher_prior_fallback_ext.py")
    rng = np.random.default_rng(1)
    starts, gpk = [], 0
    for season in (2022, 2023, 2024, 2025):
        for pid in range(300):
            for j in range(rng.integers(1, 8)):
                gpk += 1
                starts.append(_s(pid + 1000 * season, season, f"{season}-0{1 + j}-15", gpk,
                                 bb=int(rng.poisson(2)), h=int(rng.poisson(5)), er=int(rng.poisson(2.5))))
    result, md = runner.run(starts)
    assert "no picks changed" in md and "PITCHER_BB" in md and "decision" in md.lower()
    assert set(result["decision"]["markets"]) == {"PITCHER_BB", "PITCHER_HITS_ALLOWED", "PITCHER_ER"}
