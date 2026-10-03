"""Pitcher few-starts fallback research (#1482 B): scoring math and intake hook."""
from __future__ import annotations

import importlib.util
import random
from math import inf
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_pitcher_prior_research as R

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_outs_from_ip_baseball_notation():
    assert R.outs_from_ip("5.2") == 17
    assert R.outs_from_ip("6") == 18
    with pytest.raises(R.PriorResearchError):
        R.outs_from_ip("5.3")


def test_gamelog_keeps_only_starts():
    payload = {"stats": [{"splits": [
        {"date": "2025-04-01", "team": {"id": 145}, "game": {"gamePk": 1}, "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 6}},
        {"date": "2025-04-03", "team": {"id": 145}, "game": {"gamePk": 2}, "stat": {"gamesStarted": 0, "inningsPitched": "1.0", "strikeOuts": 2}},
    ]}]}
    rows = R.starts_from_gamelog(payload, pitcher_id=7, season=2025)
    assert [(r.outs, r.k, r.team_id) for r in rows] == [(16, 6, 145)]


def test_window_is_strictly_prior_and_two_seasons():
    a = R.Start(1, 2023, "2023-05-01", 1, 10, 15, 5)
    b = R.Start(1, 2024, "2024-05-01", 2, 10, 15, 5)
    c = R.Start(1, 2025, "2025-05-01", 3, 10, 15, 5)
    d = R.Start(1, 2025, "2025-05-01", 4, 10, 15, 5)  # same-day doubleheader: not prior
    w = R.prior_window_counts([a, b, c, d])
    assert w[c] == [b] and w[d] == [b] and w[b] == [a]


def test_posterior_matches_production_engine():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    pool = [{"strikeouts": k, "outs": o, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": 1}
            for k, o in [(3, 12), (5, 15), (7, 18), (6, 17), (4, 16), (8, 19)]]
    own = [R.Start(1, 2025, f"2025-04-0{i}", i, 1, r["outs"], r["strikeouts"]) for i, r in enumerate(pool, 1)]
    pred = R.predict(own, None, 0)
    for line in (14.5, 16.5):
        eng = price_pitcher_market({"market": "PITCHER_OUTS", "side": "OVER", "line": line, "features": {"history_pool": pool}})
        i = int(np.where(np.isclose(R.OUTS_THRESH, line))[0][0])
        assert pred["outs"][i] == pytest.approx(eng["model_p"], abs=1e-12)


def test_blend_interpolates_between_own_and_prior():
    own = [R.Start(1, 2025, "2025-04-01", 1, 1, 9, 2)]
    prior = {"outs": np.full(27, 0.5), "k": np.full(20, 0.5)}
    lo, mid, hi = (R.predict(own, prior, m)["outs"][15] for m in (1, 8, inf))
    own_only = R.predict(own, None, 0)["outs"][15]
    assert own_only < lo < mid < hi


def _synthetic(seed=1):
    rnd = random.Random(seed)
    starts = []
    pid = 0
    for season in (2022, 2023, 2024, 2025):
        for _ in range(60):
            pid += 1
            mu = rnd.uniform(12, 19)
            n = rnd.randint(1, 12)
            for g in range(n):
                outs = max(0, min(27, int(rnd.gauss(mu, 3))))
                starts.append(R.Start(pid, season, f"{season}-{4 + g // 4:02d}-{1 + (g % 4) * 7:02d}", pid * 100 + g, pid % 6, outs, max(0, int(rnd.gauss(outs / 3, 2)))))
    return starts


def test_end_to_end_report_on_synthetic_data():
    script = _load("prior_fb", "scripts/research_mlb_pitcher_prior_fallback.py")
    result, md = script.run(_synthetic())
    assert result["tune"]["selected"] in result["tune"]["table"]
    assert "no picks changed" in md and "Decision" in md
    assert isinstance(result["decision"]["ships"], bool)


def test_intake_research_directive_parsing():
    intake = _load("intake_mlb", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH pitcher_prior_fallback") == "pitcher_prior_fallback"
    assert intake.research_directive("Guardians -150 / White Sox +130") is None
    with pytest.raises(intake.IssueLinesError):
        intake.research_directive("RESEARCH nope")


def test_pool_artifact_counts_only_short_history_starts():
    script = _load("prior_fb_pool", "scripts/research_mlb_pitcher_prior_fallback.py")
    rnd = random.Random(4)
    starts = []
    for pid in range(1, 150):
        n = 8 if pid % 2 else 2  # odd pitchers: 8 starts -> only their first 5 are "short"
        for g in range(n):
            starts.append(R.Start(pid, 2025, f"2025-05-{1 + g:02d}", pid * 10 + g, 1, rnd.randint(3, 20), rnd.randint(0, 9)))
    art = script.build_pool_artifact(starts, 2025)
    expected = sum(min(8 if p % 2 else 2, 5) for p in range(1, 150))
    assert art["starts"] == expected
    assert sum(art["counts"]["outs"].values()) == expected == sum(art["counts"]["strikeouts"].values())
    assert art["schema"] == "MLB_PITCHER_PRIOR_POOL_V1" and art["season"] == 2025


def test_intake_knows_pool_directive():
    intake = _load("intake_mlb2", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH pitcher_prior_pool") == "pitcher_prior_pool"
    assert intake.RESEARCH_DIRECTIVES["pitcher_prior_pool"][1:] == ["--emit-pool", "2025"]
