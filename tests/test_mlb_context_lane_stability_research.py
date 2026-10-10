"""2026 context-lane stability check (#1482, 2027 prep): frozen configs, decision rule, runner, hook."""
from __future__ import annotations

import importlib.util
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_context_lane_stability_research as S
from sportsedge import mlb_opp_k_context as LANE_K
from sportsedge import mlb_opp_k_context_research as RK
from sportsedge import mlb_opp_outs_context as LANE_O
from sportsedge import mlb_opp_outs_context_research as RO
from sportsedge import mlb_umpire_bb_context as LANE_BB
from sportsedge import mlb_umpire_context_research as RU

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_frozen_configs_are_the_production_constants_and_on_the_research_grids():
    assert S.FROZEN["OPP-K"] == LANE_K.BETA == 1.0
    assert S.FROZEN["OPP-OUTS"] == (LANE_O.INDEX, LANE_O.BETA) == ("obidx", -0.25)
    assert S.FROZEN["UMP-BB"] == (LANE_BB.W, LANE_BB.BETA) == (6000.0, 2.0)
    assert S.FROZEN["OPP-K"] in RK.BETAS and S.BASELINES["OPP-K"] in RK.BETAS
    assert S.FROZEN["OPP-OUTS"] in RO.CANDIDATES and S.BASELINES["OPP-OUTS"] == RO.BASELINE
    assert S.FROZEN["UMP-BB"] in RU.CANDIDATES and S.BASELINES["UMP-BB"] == RU.BASELINE
    assert S.HELDOUT == 2026 and S.RETUNE == 2025 and S.HELDOUT in S.PITCHER_SEASONS


def _typ(ece):
    return {"n": 100.0, "logloss": 0.6, "ece": ece}


@pytest.mark.parametrize("boot,ece_b,ece_f,verdict", [
    ({"diff": -0.02, "lo": -0.03, "hi": -0.01}, 0.03, 0.03, "KEEP_CONFIRMED"),
    ({"diff": -0.001, "lo": -0.004, "hi": 0.002}, 0.03, 0.031, "KEEP_NOT_CONFIRMED"),
    ({"diff": 0.01, "lo": 0.002, "hi": 0.02}, 0.03, 0.03, "DISABLE"),
    ({"diff": -0.02, "lo": -0.03, "hi": -0.01}, 0.03, 0.0351, "DISABLE"),
    ({"diff": -0.02, "lo": -0.03, "hi": -0.01}, 0.03, 0.0349, "KEEP_CONFIRMED"),
])
def test_decision_rule(boot, ece_b, ece_f, verdict):
    d = S.stability_decision(boot, _typ(ece_b), _typ(ece_f))
    assert d["verdict"] == verdict
    assert S.verdict_text(verdict)


def test_decision_rejects_malformed_bootstrap():
    with pytest.raises(S.LaneStabilityError):
        S.stability_decision({"diff": 0.0, "lo": -0.1}, _typ(0.0), _typ(0.0))
    with pytest.raises(S.LaneStabilityError):
        S.stability_decision({"diff": 0.5, "lo": -0.1, "hi": 0.1}, _typ(0.0), _typ(0.0))


def _synthetic_raw():
    """Two teams playing each other daily; team 1 strikes out / reaches base more."""
    rng = np.random.default_rng(7)
    teams, games, sched_games = {}, {}, {}
    for season in S.TEAM_SEASONS:
        d0 = date(season, 4, 1)
        for t in (1, 2):
            teams[(t, season)] = {"stats": [{"splits": []}]}
        sched_games[season] = []
        for g in range(120):
            d = (d0 + timedelta(days=g)).isoformat()
            pk = season * 1000 + g
            games[pk] = (season, d)
            for t in (1, 2):
                k = int(rng.poisson(10 if t == 1 else 7))
                bb = int(rng.poisson(3.5))
                h = int(rng.poisson(9 if t == 1 else 7))
                teams[(t, season)]["stats"][0]["splits"].append({"date": d, "game": {"gamePk": pk}, "stat": {
                    "strikeOuts": k, "plateAppearances": 38, "baseOnBalls": bb, "hits": h, "hitByPitch": 0}})
            sched_games[season].append({"gamePk": pk, "officials": [
                {"officialType": "Home Plate", "official": {"id": 500 + g % 6}}]})
    schedules = {(s, (4, 1, 4, 30)): {"dates": [{"games": sched_games[s]}]} for s in S.TEAM_SEASONS}
    pitchers = {}
    for season in S.PITCHER_SEASONS:
        pks = [pk for pk, (s, _d) in games.items() if s == season]
        for pid in range(1, 13):
            splits = []
            for j, pk in enumerate(pks[pid % 5::5][:20]):
                team = 1 + (pid + j) % 2
                opp = 3 - team
                splits.append({"date": games[pk][1], "team": {"id": team}, "opponent": {"id": opp}, "game": {"gamePk": pk},
                               "stat": {"gamesStarted": 1, "strikeOuts": int(rng.poisson(6.5 if opp == 1 else 4.5)),
                                        "baseOnBalls": int(rng.poisson(2.0)), "inningsPitched": f"{int(rng.integers(4, 7))}.{int(rng.integers(0, 3))}"}})
            pitchers[(pid, season)] = {"stats": [{"splits": splits}]}
    return {"pitchers": pitchers, "teams": teams, "schedules": schedules}


def test_runner_end_to_end_on_synthetic_logs(tmp_path):
    runner = _load("lane_stability_runner", "scripts/research_mlb_context_lane_stability_2026.py")
    raw = _synthetic_raw()
    lanes = [runner.lane_opp_k(raw), runner.lane_opp_outs(raw), runner.lane_ump_bb(raw)]
    assert [x["lane"] for x in lanes] == ["OPP-K", "OPP-OUTS", "UMP-BB"]
    for x in lanes:
        assert x["units"]["heldout_2026"] > 0 and x["units"]["retune_2025"] > 0
        assert x["decision"]["verdict"] in {"DISABLE", "KEEP_CONFIRMED", "KEEP_NOT_CONFIRMED"}
        b = x["decision"]["bootstrap_frozen_minus_base"]
        assert b["diff"] == pytest.approx(x["heldout_rps"]["frozen"] - x["heldout_rps"]["baseline"], abs=1e-12)
    assert lanes[2]["umpire_coverage"]["share"] == pytest.approx(1.0)
    md = runner.report(lanes)
    assert "no picks changed" in md and "held-out 2026" in md and S.prereg_sha256()[:16] in md


def test_frozen_opp_k_price_equals_production_engine_math():
    """The runner scores RK.predict_k at the frozen beta, which #1513 pins to the engine."""
    idx = RK.OppIndex({(1, 2025): [("2025-04-01", 20, 100)], (2, 2025): [("2025-04-01", 10, 100)],
                       (1, 2026): [("2026-04-01", 20, 100)], (2, 2026): [("2026-04-01", 10, 100)]})
    own = [RK.KStart(1, 2026, f"2026-04-0{i}", i, 10, 1 + i % 2, k) for i, k in enumerate([4, 5, 6, 5, 4], 1)]
    tgt = RK.KStart(1, 2026, "2026-04-20", 99, 10, 1, 0)
    assert not np.allclose(RK.predict_k(own, tgt, idx, S.FROZEN["OPP-K"]), RK.predict_k(own, tgt, idx, 0.0))


def test_prereg_and_intake_hook():
    text = S.PREREG_PATH.read_text()
    assert "RESEARCH context_lane_stability_2026" in text and "DISABLE for 2027" in text
    intake = _load("intake_lane_stability", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH context_lane_stability_2026") == "context_lane_stability_2026"
    script = intake.RESEARCH_DIRECTIVES["context_lane_stability_2026"]
    assert script == ["scripts/research_mlb_context_lane_stability_2026.py"] and (ROOT / script[0]).exists()
    assert intake.RESEARCH_TIMEOUT_SECONDS["context_lane_stability_2026"] >= 20 * 60
    cov = (ROOT / "config" / "reconciliation_coverage_v1.json").read_text()
    assert "docs/MLB_CONTEXT_LANE_STABILITY_2026_PREREG.md" in cov
