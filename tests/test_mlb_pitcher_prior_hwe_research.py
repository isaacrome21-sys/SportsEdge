"""Few-starts fallback H+W+ER extension research (#1482): math, parity and intake hook."""
from __future__ import annotations

import hashlib
import importlib.util
import random
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_pitcher_prior_ext_research as X
from sportsedge import mlb_pitcher_prior_hwe_research as H
from sportsedge import mlb_pitcher_prior_research as R

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _s(pid, season, date, gpk, bb=1, h=4, er=2, outs=15, k=5, team=10):
    return X.XStart(pid, season, date, gpk, team, outs, k, bb, h, er)


def test_frozen_candidate_and_prereg_binding():
    assert (H.POOL, H.M, H.MARKET) == ("league_short", 4.0, "PITCHER_HITS_WALKS_ER")
    assert H.prereg_sha256() == hashlib.sha256(H.PREREG_PATH.read_bytes()).hexdigest()
    assert list(H.THRESH) == [t + 0.5 for t in range(25)]
    assert all(np.isclose(H.THRESH, t).any() for t in H.TYPICAL)


def test_hwe_is_per_start_sum():
    assert H.hwe(_s(1, 2025, "2025-04-01", 1, bb=2, h=5, er=3)) == 10


@pytest.mark.parametrize("k", [1, 2, 3, 4])
def test_fallback_formula_equals_production_engine_fallback(k):
    """Same arithmetic as pitcher_joint_engine._price_prior_fallback (checked via the PITCHER_K path)."""
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    rnd = random.Random(100 + k)
    own = [_s(1, 2025, f"2025-04-0{i + 1}", i + 1, bb=rnd.randint(0, 4), h=rnd.randint(0, 9), er=rnd.randint(0, 6)) for i in range(k)]
    prior_vals = [rnd.randint(0, 24) for _ in range(400)]
    counts: dict[str, int] = {}
    for v in prior_vals:
        counts[str(v)] = counts.get(str(v), 0) + 1
    pred = H.predict_fallback(own, H._over_frac(prior_vals))
    pool = [{"strikeouts": H.hwe(s), "outs": 15, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1} for s in own]
    for i, line in enumerate(H.THRESH):
        eng = price_pitcher_market({"market": "PITCHER_K", "side": "OVER", "line": float(line), "features": {
            "history_pool": pool, "prior_fallback": {"market": "PITCHER_K", "pseudo_starts": 4.0, "counts": counts, "pool": "league_short", "season": 2025}}})
        assert pred[i] == pytest.approx(eng["model_p"], abs=1e-12, rel=0)


def test_own_only_matches_production_hwe_for_k_ge_5():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    rows = [(0, 3, 1), (2, 6, 3), (1, 4, 0), (3, 8, 5), (1, 5, 2), (0, 2, 0)]
    pool = [{"strikeouts": 5, "outs": 15, "earned_runs": er, "hits_allowed": h, "walks_allowed": bb} for bb, h, er in rows]
    own = [_s(1, 2025, f"2025-04-0{i + 1}", i + 1, bb=bb, h=h, er=er) for i, (bb, h, er) in enumerate(rows)]
    pred = H.predict_own(own)
    for line in H.TYPICAL + (0.5, 15.5):
        eng = price_pitcher_market({"market": "PITCHER_HITS_WALKS_ER", "side": "OVER", "line": line, "features": {"history_pool": pool}})
        i = int(np.where(np.isclose(H.THRESH, line))[0][0])
        assert pred[i] == pytest.approx(eng["model_p"], abs=1e-12, rel=0)


def test_values_above_cap_clip_into_top_bin():
    over = H._over_frac([30, 0])
    assert over[-1] == pytest.approx(0.5) and over[0] == pytest.approx(0.5)


def test_pool_uses_only_short_history_prior_season_starts():
    starts = [_s(1, 2023, f"2023-0{m}-01", m, bb=3, h=9, er=8) for m in range(4, 10)]  # 6 starts: last is k=5
    starts += [_s(100 + i, 2023, "2023-05-01", 1000 + i, bb=0, h=0, er=0) for i in range(120)]  # debuts, hwe=0
    window = R.prior_window_counts(starts)
    pool = H.league_short_pool(starts, window)
    assert pool[0] == pytest.approx(5 / 125)  # only pitcher 1's first five starts (hwe=20) are > 0.5


def _synthetic(seasons, n_pitchers, max_starts, seed):
    rng = np.random.default_rng(seed)
    starts, gpk = [], 0
    for season in seasons:
        for pid in range(n_pitchers):
            for j in range(rng.integers(1, max_starts)):
                gpk += 1
                starts.append(_s(pid + 1000 * season, season, f"{season}-0{1 + j}-15", gpk,
                                 bb=int(rng.poisson(2)), h=int(rng.poisson(5)), er=int(rng.poisson(2.5))))
    return starts


def test_decision_on_homogeneous_synthetic_signal():
    starts = _synthetic((2023, 2024, 2025), 400, 4, 0)
    window = R.prior_window_counts(starts)
    by = {y: [s for s in starts if s.season == y] for y in (2023, 2024, 2025)}
    test = H.evaluate(by[2025], window, H.league_short_pool(by[2024], window), ks=range(1, 5))
    cons = H.evaluate(by[2024], window, H.league_short_pool(by[2023], window), ks=range(1, 5))
    assert test and all(1 <= r["k"] <= 4 and {"own", "fallback"} <= set(r["preds"]) for r in test)
    ref = [{**r, "preds": {"own": r["preds"]["own"]}} for r in test]
    d = H.ship_decision(test, cons, ref)
    assert d["test_vs_own"]["hi"] < 0 and d["rule3_sign_2024"]


def test_intake_has_research_directives():
    intake = _load("mlb_intake_hwe", "scripts/intake_mlb_lines_issue.py")
    assert intake.RESEARCH_DIRECTIVES["pitcher_prior_fallback_hwe"] == ["scripts/research_mlb_pitcher_prior_fallback_hwe.py"]
    assert intake.RESEARCH_DIRECTIVES["pitcher_prior_pool_hwe"] == ["scripts/research_mlb_pitcher_prior_fallback_hwe.py", "--emit-pool", "2025"]
    assert intake.research_directive("RESEARCH pitcher_prior_fallback_hwe") == "pitcher_prior_fallback_hwe"


def test_runner_report_and_pool_artifact_on_synthetic_starts():
    runner = _load("prior_hwe_runner", "scripts/research_mlb_pitcher_prior_fallback_hwe.py")
    starts = _synthetic((2022, 2023, 2024, 2025), 300, 8, 1)
    result, md = runner.run(starts)
    assert "no picks changed" in md and "PITCHER_HITS_WALKS_ER" in md
    assert result["decision"]["market"] == "PITCHER_HITS_WALKS_ER"
    art = runner.build_hwe_pool_artifact([s for s in starts if s.season in (2024, 2025)], 2025)
    assert set(art["counts"]) == {"outs", "strikeouts", "hits_walks_er"}
    assert sum(art["counts"]["hits_walks_er"].values()) == art["starts"] == sum(art["counts"]["outs"].values())
