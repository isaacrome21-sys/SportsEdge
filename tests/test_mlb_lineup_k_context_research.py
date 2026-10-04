"""Context lane 2c research (#1482 D2c): announced-lineup K -> pitcher K math, parity, intake hook."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from sportsedge import mlb_lineup_k_context_research as R
from sportsedge.mlb_opp_k_context_research import OppIndex, production_window
from sportsedge.mlb_umpire_context_research import UStart

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_schedule_keeps_only_final_regular_season_games():
    sched = {"dates": [{"date": "2025-04-01", "games": [
        {"gamePk": 1, "gameType": "R", "officialDate": "2025-04-01", "status": {"abstractGameState": "Final", "codedGameState": "F"}},
        {"gamePk": 2, "gameType": "R", "officialDate": "2025-04-01", "status": {"abstractGameState": "Final", "codedGameState": "D"}},
        {"gamePk": 3, "gameType": "S", "officialDate": "2025-04-01", "status": {"abstractGameState": "Final", "codedGameState": "F"}},
        {"gamePk": 4, "gameType": "R", "officialDate": "2025-04-01", "status": {"abstractGameState": "Preview"}},
    ]}]}
    assert R.final_games_from_schedule(sched) == {1: "2025-04-01"}


def _box(order_away, order_home, lines):
    def side(tid, order):
        return {"team": {"id": tid}, "battingOrder": order,
                "players": {f"ID{p}": {"person": {"id": p}, "stats": {"batting": lines.get(p, {})}} for p in set(order) | set(lines)}}
    return {"teams": {"away": side(10, order_away), "home": side(20, order_home)}}


def test_parse_boxscore_orders_and_lines():
    lines = {1: {"strikeOuts": 2, "plateAppearances": 4}, 2: {"strikeOuts": 0, "atBats": 3, "baseOnBalls": 1}, 3: {}}
    box = R.parse_boxscore(_box(list(range(1, 10)), [5, 5, 6, 7, 8, 9, 10, 11, 12], lines))
    assert box["orders"][10] == tuple(range(1, 10))
    assert box["orders"][20] is None  # duplicate batter -> unknown
    assert box["lines"][1] == (2, 4) and box["lines"][2] == (0, 4) and 3 not in box["lines"]


def _team_rows():
    # League K/PA 0.20 in 2024; 2025 before any date adds 0.25.
    return {(1, 2024): [("2024-05-01", 20, 100)], (2, 2024): [("2024-05-01", 20, 100)],
            (1, 2025): [("2025-04-01", 25, 100)], (2, 2025): [("2025-04-01", 25, 100)]}


def test_rates_are_strictly_prior_two_season_and_shrunk():
    batters = {7: [("2024-06-01", 30, 100), ("2025-04-01", 10, 20), ("2025-04-10", 9, 9)]}
    idx = R.LineupIndex(_team_rows(), batters)
    assert idx.league_rate("2025-04-01", 2025) == pytest.approx(40 / 200)  # same-day excluded
    assert idx.league_rate("2025-04-02", 2025) == pytest.approx(90 / 400)
    r_l = 90 / 400
    assert idx.batter_rate(7, "2025-04-05", 2025, 200.0) == pytest.approx((40 + 200 * r_l) / (120 + 200))
    assert idx.batter_rate(99, "2025-04-05", 2025, 200.0) == pytest.approx(r_l)  # unknown batter -> league
    # 2023 data is outside the Y-1/Y window for 2025.
    old = R.LineupIndex({**_team_rows(), (1, 2023): [("2023-05-01", 90, 100)]}, {7: [("2023-06-01", 90, 100)]})
    assert old.batter_rate(7, "2025-04-05", 2025, 200.0) == pytest.approx(r_l)
    order = (7,) + tuple(range(100, 108))
    lrel = idx.lineup_rel(order, "2025-04-05", 2025, 200.0)
    want = (R.SLOT_WEIGHTS[0] * idx.batter_rate(7, "2025-04-05", 2025, 200.0) + sum(R.SLOT_WEIGHTS[1:]) * r_l) / (r_l * sum(R.SLOT_WEIGHTS))
    assert lrel == pytest.approx(want) and lrel > 1.0
    with pytest.raises(R.LineupResearchError):
        idx.lineup_rel(order[:8], "2025-04-05", 2025, 200.0)


def _opp():
    rows = {}
    for season in (2024, 2025):
        rows[(1, season)] = [(f"{season}-04-01", 30, 100)]
        rows[(2, season)] = [(f"{season}-04-01", 15, 100)]
    return OppIndex(rows)


def _pool():
    return [{"strikeouts": k, "outs": o, "earned_runs": 1, "hits_allowed": 4, "walks_allowed": bb}
            for k, o, bb in [(3, 12, 1), (5, 15, 3), (7, 18, 0), (6, 17, 2), (4, 16, 4), (8, 19, 1)]]


def test_baseline_matches_production_opp_k_engine():
    from sportsedge.pitcher_joint_engine import price_pitcher_market
    opp = _opp()
    pool = _pool()
    own = [UStart(1, 2025, f"2025-04-0{i + 2}", 1000 + i, 10, 2 if i % 2 else 1, r["strikeouts"], r["walks_allowed"]) for i, r in enumerate(pool)]
    target = UStart(1, 2025, "2025-04-20", 2000, 10, 1, 0, 0)
    lidx = R.LineupIndex(_team_rows(), {})
    pred = R.predict(own, target, {}, lidx, opp, R.BASELINE)
    adj = {"market": "PITCHER_K", "beta": 1.0, "target_rel": opp.rel(1, 2025, target.date),
           "history_rel": [opp.rel(r.opp_id, r.season, r.date) for r in own]}
    for line in np.arange(0, 20) + 0.5:
        for side in ("OVER", "UNDER"):
            eng = price_pitcher_market({"market": "PITCHER_K", "side": side, "line": float(line),
                                        "features": {"history_pool": pool, "opp_k_adjustment": adj}})
            i = int(np.where(np.isclose(R.THRESH, line))[0][0])
            assert (pred[i] if side == "OVER" else 1 - pred[i]) == pytest.approx(eng["model_p"], abs=1e-12)


def test_adjustment_direction_and_unknown_history_lineup():
    opp = _opp()
    contact = tuple(range(200, 209))
    whiff = tuple(range(300, 309))
    batters = {b: [("2024-06-01", 10, 100)] for b in contact}
    batters.update({b: [("2024-06-01", 35, 100)] for b in whiff})
    lidx = R.LineupIndex(_team_rows(), batters)
    own = [UStart(1, 2025, f"2025-04-0{i + 2}", 500 + i, 10, 2, 5, 2) for i in range(6)]
    lineups = {s.game_pk: {2: contact} for s in own}
    target = UStart(1, 2025, "2025-04-20", 900, 10, 2, 0, 0)
    lineups[900] = {2: whiff}
    i = int(np.where(np.isclose(R.THRESH, 6.5))[0][0])
    base = R.predict(own, target, lineups, lidx, opp, R.BASELINE)[i]
    assert R.predict(own, target, lineups, lidx, opp, (200.0, 0.5))[i] > base
    assert R.predict(own, target, lineups, lidx, opp, (200.0, 1.0))[i] > R.predict(own, target, lineups, lidx, opp, (200.0, 0.5))[i]
    # Unknown history lineups count as D_i = 1.
    unknown = {900: {2: whiff}}
    d_t = R.deviation(target, unknown, lidx, opp, 200.0)
    got = R.predict(own, target, unknown, lidx, opp, (200.0, 1.0))
    xs = [5.0 * d_t for _ in own]
    from sportsedge.mlb_pitcher_prior_research import posterior_over
    from sportsedge.mlb_umpire_context_research import adjusted_mass_over
    assert np.allclose(got, posterior_over(adjusted_mass_over(xs, "k"), 6.0), atol=1e-12)
    with pytest.raises(R.LineupResearchError):
        R.predict(own, UStart(1, 2025, "2025-04-20", 901, 10, 2, 0, 0), lineups, lidx, opp, (200.0, 0.5))


def test_select_ties_and_candidates():
    table = {c: 1.0 for c in R.CANDIDATES}
    assert R.select(table) == R.BASELINE
    table[(600.0, 0.75)] = 0.9
    assert R.select(table) == (600.0, 0.75)
    assert len(R.CANDIDATES) == 9 and R.CANDIDATES[0] == R.BASELINE


def _synthetic(lineup_effect: bool = True):
    """Team 2's lineup alternates between contact and whiff regulars; pitcher K follows it."""
    rng = np.random.default_rng(11)
    contact = list(range(200, 209))
    whiff = list(range(300, 309))
    games, boxes, teams, starts = {}, {}, {}, []
    pk = 0
    for season in (2022, 2023, 2024, 2025):
        for t in (1, 2):
            teams[(t, season)] = []
        for day in range(1, 120):
            d = (np.datetime64(f"{season}-04-01") + np.timedelta64(day, "D")).astype(str)
            pk += 1
            games[pk] = d
            order2 = whiff if day % 3 == 0 else contact
            order1 = list(range(100, 109))
            lines = []
            k2 = 0
            for b in order2:
                p = 0.33 if b in whiff else 0.16
                k = int(rng.binomial(4, p))
                k2 += k
                lines.append([b, k, 4])
            for b in order1:
                lines.append([b, int(rng.binomial(4, 0.22)), 4])
            boxes[pk] = {"orders": [[1, order1], [2, order2]], "lines": lines}
            teams[(2, season)].append((pk, d, k2, 3, 36))
            teams[(1, season)].append((pk, d, sum(x[1] for x in lines[9:]), 3, 36))
            if season >= 2023:
                for pid in range(8):
                    if (day + pid) % 4 == 0:
                        lam = (7.5 if order2 is whiff else 4.0) if lineup_effect else 5.0
                        starts.append(UStart(pid, season, d, pk, 1, 2, int(rng.poisson(lam)), 2))
    return games, boxes, teams, starts


def test_runner_end_to_end_on_synthetic_logs():
    runner = _load("lineup_runner", "scripts/research_mlb_lineup_k_context.py")
    games, boxes, teams, starts = _synthetic()
    assert len(production_window(starts)) == len(starts)
    result, md = runner.run(games, boxes, teams, starts)
    assert "held-out validation" in md and "no picks changed" in md
    assert result["tune_units"] > 0 and result["test_units"] > 0
    assert len(result["test_rps"]) == 9
    # The synthetic lineup effect is strong and invisible to the team index, so it should be selected and help.
    assert result["selected"] != "baseline (production)"
    assert result["decision"]["bootstrap_vs_base"]["diff"] < 0


def test_runner_refuses_missing_batting_orders():
    runner = _load("lineup_runner2", "scripts/research_mlb_lineup_k_context.py")
    games, boxes, teams, starts = _synthetic()
    sparse = {pk: ({"orders": [[1, None], [2, None]], "lines": b["lines"]} if pk % 3 else b) for pk, b in boxes.items()}
    with pytest.raises(RuntimeError, match="batting orders"):
        runner.run(games, sparse, teams, starts)


def test_intake_registers_directive_and_prereg_is_mapped():
    intake = _load("intake_lineup", "scripts/intake_mlb_lines_issue.py")
    assert intake.research_directive("RESEARCH lineup_k_context") == "lineup_k_context"
    assert intake.RESEARCH_DIRECTIVES["lineup_k_context"] == ["scripts/research_mlb_lineup_k_context.py"]
    assert (ROOT / intake.RESEARCH_DIRECTIVES["lineup_k_context"][0]).exists()
    assert "docs/MLB_LINEUP_K_CONTEXT_PREREG.md" in (ROOT / "config" / "reconciliation_coverage_v1.json").read_text()
    assert len(R.prereg_sha256()) == 64


def test_runner_does_not_ship_without_a_lineup_effect():
    runner = _load("lineup_runner3", "scripts/research_mlb_lineup_k_context.py")
    games, boxes, teams, starts = _synthetic(lineup_effect=False)
    result, _md = runner.run(games, boxes, teams, starts)
    assert result["decision"]["ships"] is False
