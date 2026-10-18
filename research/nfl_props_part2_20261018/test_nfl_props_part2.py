"""Part 2 forward-test package tests (frozen prereg §4-§5 enforcement).

Run: python3 -m pytest research/nfl_props_part2_20261018/test_nfl_props_part2.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import price_nfl_props_part2 as pricing  # noqa: E402
import score_nfl_props_part2 as scoring  # noqa: E402

EV = pricing.load_evaluator()
GRID = np.arange(EV.GRID_LO, EV.GRID_HI + 1, dtype=float)


# ---------- (a) the evaluator import is the verified one, wired unchanged ----------

def test_evaluator_file_matches_pinned_hash():
    digest = hashlib.sha256((HERE / pricing.EVALUATOR_NAME).read_bytes()).hexdigest()
    assert digest == pricing.EVALUATOR_SHA256
    assert digest == "66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b"


def test_evaluator_construction_constants():
    assert EV.K == 3.0
    assert set(EV.MARKETS) == {"PASS_YDS", "RUSH_YDS", "REC_YDS", "RECEPTIONS"}
    assert EV.TRAIN == (2018, 2019)


def test_mu_for_hand_computed():
    # (100+200+300 + 3*150) / (3+3) = 1050/6 = 175
    assert EV.mu_for([100.0, 200.0, 300.0], [150.0]) == pytest.approx(175.0)


def test_candidate_cdf_matches_scipy_gamma_on_grid():
    mu, cv = 215.0, 0.35
    cdf = EV.candidate_cdf(mu, cv, False, GRID)
    shape = 1.0 / (cv * cv)
    at_200 = cdf[200 - EV.GRID_LO]
    assert at_200 == pytest.approx(stats.gamma.cdf(200, shape, scale=mu / shape), abs=1e-12)


def test_candidate_cdf_receptions_is_negbin():
    mu, cv = 5.0, 0.6
    cdf = EV.candidate_cdf(mu, cv, True, GRID)
    var = (cv * mu) ** 2
    r = mu * mu / (var - mu)
    assert cdf[5 - EV.GRID_LO] == pytest.approx(
        stats.nbinom.cdf(5, r, r / (r + mu)), abs=1e-12)


def test_p_over_monotone_and_bounded():
    hi = pricing.p_over_for(EV, 215.0, 0.35, False, 180.5, GRID)
    mid = pricing.p_over_for(EV, 215.0, 0.35, False, 232.5, GRID)
    lo = pricing.p_over_for(EV, 215.0, 0.35, False, 300.5, GRID)
    assert 0.0 < lo < mid < hi < 1.0


def _synthetic_season(qb_games):
    """evaluator.load-shaped data: {season: {pid: [(week, pos, row)]}}."""
    def row(att, py):
        return {"attempts": att, "passing_yards": py, "carries": 0.0,
                "rushing_yards": 0.0, "targets": 0.0, "receptions": 0.0,
                "receiving_yards": 0.0}
    return {2026: {"QB1": [(w, "QB", row(30.0, y)) for w, y in qb_games]}}


def test_price_rows_qualification_and_mu():
    data = _synthetic_season([(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)])
    capture = {"season": 2026, "week": 5, "rows": [
        {"game_id": "G1", "player_id": "QB1", "market": "PASS_YDS", "line": 232.5,
         "over_price": -112, "under_price": -108,
         "captured_at": "2026-10-22T18:00:00-05:00", "kickoff": "2026-10-22T19:20:00-05:00"},
        {"game_id": "G1", "player_id": "GHOST", "market": "PASS_YDS", "line": 232.5,
         "over_price": -112, "under_price": -108,
         "captured_at": "2026-10-22T18:00:00-05:00", "kickoff": "2026-10-22T19:20:00-05:00"},
    ]}
    cvs = {m: 0.35 for m in EV.MARKETS}
    rows, pools = pricing.price_rows(EV, data, capture, cvs)
    priced = next(r for r in rows if r["player_id"] == "QB1")
    assert priced["status"] == "PRICED"
    # pool = [260] (only the week-4 qualified outcome); mu = (920 + 3*260)/7
    assert priced["mu"] == pytest.approx((920.0 + 780.0) / 7.0)
    assert priced["games_logged"] == 4
    assert priced["shrink_weight"] == pytest.approx(3.0 / 7.0)
    assert priced["cv_source"] == "POOLED"
    assert 0.0 < priced["p_over"] < 1.0
    ghost = next(r for r in rows if r["player_id"] == "GHOST")
    assert ghost["status"] == "NOT_QUALIFIED"
    assert ghost["reason"] == "ONLY_0_PRIOR_GAMES"


# ---------- (b) CLV_MISSING: labeled, out of CLV, still in win/loss ----------

def _priced_row(pid, game, *, selected="OVER", close_status="AWAITING_CLOSE"):
    nv_o, nv_u = pricing.devig_pair(-110, -110)
    return {"row_id": f"{game}|{pid}|REC_YDS|45.5", "game_id": game,
            "player_id": pid, "player_name": pid, "market": "REC_YDS",
            "line": 45.5, "over_price": -110, "under_price": -110,
            "captured_at": "2026-10-22T18:00:00-05:00",
            "kickoff": "2026-10-22T19:20:00-05:00",
            "status": "PRICED", "mu": 50.0, "cv": 0.741, "cv_source": "POOLED",
            "games_logged": 5, "shrink_weight": 0.375, "pool_mean": 47.7,
            "prior_values": [40.0, 55.0, 48.0, 62.0, 45.0],
            "p_over": 0.58, "p_under": 0.42,
            "ev_over": 0.05, "ev_under": -0.10, "selected_side": selected,
            "entry_novig_p_over": nv_o, "entry_novig_p_under": nv_u,
            "close_status": close_status, "close_over_price": None,
            "close_under_price": None, "close_captured_at": None,
            "close_novig_p_over": None, "close_novig_p_under": None}


def test_missing_close_labeled_and_scored_correctly(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    rows = [_priced_row("P_A", "G1", selected="OVER"),
            _priced_row("P_B", "G1", selected="UNDER")]
    (run_dir / "priced_rows.json").write_text(json.dumps({"run": {}, "rows": rows}))
    (run_dir / "pools.json").write_text(json.dumps({"REC_YDS": [40.0, 50.0, 60.0]}))
    close = {"season": 2026, "week": 5, "rows": [
        {"game_id": "G1", "player_id": "P_A", "market": "REC_YDS", "line": 45.5,
         "over_price": -130, "under_price": 110,
         "captured_at": "2026-10-22T19:00:00-05:00", "kickoff": "2026-10-22T19:20:00-05:00"},
        # P_B absent -> no readable two-sided close
    ]}
    close_path = tmp_path / "close.json"
    close_path.write_text(json.dumps(close))
    summary = pricing.attach_close(run_dir, close_path)
    assert summary == {"readable": 1, "clv_missing": 1}
    payload = json.loads((run_dir / "priced_rows.json").read_text())
    by_pid = {r["player_id"]: r for r in payload["rows"]}
    assert by_pid["P_A"]["close_status"] == "READABLE"
    assert by_pid["P_B"]["close_status"] == "CLV_MISSING"
    assert by_pid["P_B"]["clv_missing_reason"] == "NO_CLOSE_ROW"

    outcomes = {"results": [{"player_id": "P_A", "market": "REC_YDS", "value": 60.0},
                            {"player_id": "P_B", "market": "REC_YDS", "value": 30.0}]}
    scored, _ = scoring.score_runs(EV, [run_dir], outcomes)
    agg = scoring.aggregate_market(EV, scored, slates_completed=1, passing_graded_rows=0)
    # both rows stay in win/loss (A: OVER won; B: UNDER won)
    assert agg["win_loss"]["wins"] == 2 and agg["win_loss"]["losses"] == 0
    # only the readable row enters CLV
    assert agg["clv_missing_rows"] == 1
    assert agg["clv_missing_share"] == pytest.approx(0.5)
    assert agg["clv"]["n"] == 1
    expected_clv = by_pid["P_A"]["close_novig_p_over"] - by_pid["P_A"]["entry_novig_p_over"]
    assert agg["clv"]["mean"] == pytest.approx(expected_clv)
    assert expected_clv > 0  # close moved toward the model's side


# ---------- (c) the >20% CLV_MISSING rule flips the market verdict ----------

def _scored_market(n_rows=100, n_missing=21, n_games=40):
    rows = []
    for i in range(n_rows):
        game = f"G{i % n_games}"
        row = _priced_row(f"P{i}", game, selected="OVER")
        if i < n_missing:
            row["close_status"] = "CLV_MISSING"
            row["clv_missing_reason"] = "NO_CLOSE_ROW"
        else:
            row["close_status"] = "READABLE"
            nv_o, nv_u = pricing.devig_pair(-110, -110)
            row["close_novig_p_over"] = nv_o + 0.05  # uniform +5pt CLV
            row["close_novig_p_under"] = nv_u - 0.05
        rows.append(scoring.score_row(EV, row, [40.0, 50.0, 60.0], 60.0, GRID))
    return rows


def test_over_20pct_missing_close_is_insufficient_close_data():
    rows = _scored_market(n_missing=21)
    agg = scoring.aggregate_market(EV, rows, slates_completed=4, passing_graded_rows=50)
    assert agg["graded_rows"] == 100 and agg["distinct_games"] == 40
    assert agg["clv_missing_share"] == pytest.approx(0.21)
    assert agg["clv"]["mean"] > 0  # the CLV signal itself is positive...
    assert agg["verdict"] == "INSUFFICIENT_CLOSE_DATA"  # ...and still no verdict


def test_exactly_20pct_missing_close_still_allows_verdict():
    rows = _scored_market(n_missing=20)
    agg = scoring.aggregate_market(EV, rows, slates_completed=4, passing_graded_rows=50)
    assert agg["clv_missing_share"] == pytest.approx(0.20)
    assert agg["verdict"] == "BEATS_MARKET"


def test_verdict_gates_order():
    base = dict(slates_completed=4, passing_graded_rows=50, graded_rows=100,
                distinct_games=40, clv_missing_share=0.0, clv_ci_lo=0.01)
    assert scoring.market_verdict(**base) == "BEATS_MARKET"
    assert scoring.market_verdict(**{**base, "graded_rows": 99}) == "INSUFFICIENT_SAMPLE"
    assert scoring.market_verdict(**{**base, "slates_completed": 3}) == "REVIEW_NOT_OPEN"
    assert scoring.market_verdict(**{**base, "passing_graded_rows": 49}) == "REVIEW_NOT_OPEN"
    assert scoring.market_verdict(**{**base, "distinct_games": 39}) == "REVIEW_NOT_OPEN"
    assert scoring.market_verdict(**{**base, "clv_ci_lo": -0.01}) == "DOES_NOT_BEAT_MARKET"


# ---------- (d) the frozen document carries the frozen terms ----------

def test_frozen_prereg_terms_present():
    text = (HERE / pricing.PREREG_NAME).read_text()
    assert "Status: FROZEN" in text
    for term in ("CLV_MISSING", "INSUFFICIENT_CLOSE_DATA", "INSUFFICIENT_SAMPLE",
                 "BEATS_MARKET", "DOES_NOT_BEAT_MARKET", "SMALL-N ARTIFACT",
                 "ROLE POOLS", "HISTORICAL", "POOLED", "WITHIN-PLAYER"):
        assert term in text, term
    for term in ("4 full slates", "50 graded passing-yards rows",
                 "40 distinct games per market", "100 graded rows", "20%",
                 "1–3, 4–5, 6–9, 10+", "w ≥ 0.43", "0.25 ≤ w <"):
        assert term in text, term
    # the boundary: Oct 18 rows are historical, never prospective
    assert "never prospective entries" in text
    assert "never in the prospective sample" in text
    # owner fix (Oct 18): every threshold is an exact number — no hedging
    # qualifier on any threshold anywhere in the frozen document
    for hedge in ("~40", "~50", "~100", "~20", "about 40", "about 50",
                  "approximately", "around 40", "roughly"):
        assert hedge not in text, hedge


def test_under_rate_stratification_buckets():
    rows = []
    for n, sel in ((3, "UNDER"), (5, "OVER"), (9, "UNDER"), (12, "UNDER")):
        r = _priced_row(f"P{n}", "G1", selected=sel)
        r["games_logged"] = n
        r["shrink_weight"] = 3.0 / (n + 3.0)
        rows.append(r)
    table = scoring.under_rate(rows)
    assert table["overall"] == {"n": 4, "under": 3, "under_rate": 0.75}
    assert table["by_games_logged"]["1-3"]["under_rate"] == 1.0
    assert table["by_games_logged"]["10+"]["under_rate"] == 1.0
    assert table["by_shrink_weight"]["w>=0.43"]["n"] == 1  # only n=3 -> w=0.50
    assert table["by_shrink_weight"]["0.25<=w<0.43"]["n"] == 2  # n=5 -> .375, n=9 -> .25
    assert table["by_shrink_weight"]["w<0.25"]["n"] == 1  # n=12 -> .20
