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


def _attach(tmp_path, rows, close_rows):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "priced_rows.json").write_text(json.dumps({"run": {}, "rows": rows}))
    close_path = tmp_path / "close.json"
    close_path.write_text(json.dumps({"season": 2026, "week": 5, "rows": close_rows}))
    summary = pricing.attach_close(run_dir, close_path)
    payload = json.loads((run_dir / "priced_rows.json").read_text())
    return summary, {r["player_id"]: r for r in payload["rows"]}


def _close(pid, line=45.5, captured="2026-10-22T19:00:00-05:00", over=-130, under=110):
    return {"game_id": "G1", "player_id": pid, "market": "REC_YDS", "line": line,
            "over_price": over, "under_price": under, "captured_at": captured,
            "kickoff": "2026-10-22T19:20:00-05:00"}


def test_moved_line_is_line_moved_never_repriced(tmp_path):
    # P_A's market closed at 47.5 (entry 45.5); P_B has no market at all.
    summary, by = _attach(tmp_path, [_priced_row("P_A", "G1"), _priced_row("P_B", "G1")],
                          [_close("P_A", line=47.5)])
    assert summary == {"readable": 0, "clv_missing": 2}
    assert by["P_A"]["clv_missing_reason"] == "LINE_MOVED"
    assert by["P_A"]["close_novig_p_over"] is None  # never repriced to the new line
    assert by["P_B"]["clv_missing_reason"] == "NO_CLOSE_ROW"


def test_close_freshness_boundary_60_minutes(tmp_path):
    # kickoff 19:20 -> 18:20 is exactly 60 min (readable); 18:19 is 61 min (stale)
    summary, by = _attach(
        tmp_path,
        [_priced_row("P_A", "G1"), _priced_row("P_B", "G1"), _priced_row("P_C", "G1")],
        [_close("P_A", captured="2026-10-22T18:20:00-05:00"),
         _close("P_B", captured="2026-10-22T18:19:00-05:00"),
         _close("P_C", captured="2026-10-22T19:20:00-05:00")])
    assert by["P_A"]["close_status"] == "READABLE"
    assert by["P_B"]["clv_missing_reason"] == "CLOSE_STALE"
    assert by["P_C"]["clv_missing_reason"] == "CLOSE_NOT_PREKICKOFF"
    assert summary == {"readable": 1, "clv_missing": 2}


def test_single_sided_close_reason(tmp_path):
    _, by = _attach(tmp_path, [_priced_row("P_A", "G1")], [_close("P_A", under=None)])
    assert by["P_A"]["clv_missing_reason"] == "CLOSE_SINGLE_SIDED"


def test_missing_share_reported_by_reason():
    rows = []
    for i, reason in enumerate(["LINE_MOVED", "LINE_MOVED", "CLOSE_STALE", None, None]):
        row = _priced_row(f"P{i}", f"G{i}")
        if reason:
            row["close_status"] = "CLV_MISSING"
            row["clv_missing_reason"] = reason
        else:
            row["close_status"] = "READABLE"
            nv_o, nv_u = pricing.devig_pair(-110, -110)
            row["close_novig_p_over"], row["close_novig_p_under"] = nv_o, nv_u
        rows.append(scoring.score_row(EV, row, [40.0, 50.0, 60.0], 60.0, GRID))
    agg = scoring.aggregate_market(EV, rows, slates_completed=1, passing_graded_rows=0)
    assert agg["clv_missing_rows"] == 3
    assert agg["clv_missing_by_reason"] == {"CLOSE_STALE": 1, "LINE_MOVED": 2}


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
                 "1–3, 4–5, 6–9, 10+", "w ≥ 0.43", "0.25 ≤ w <",
                 "LINE_MOVED", "CLOSE_STALE", "no more than 60 minutes before kickoff"):
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


# ---------- (g) capture-contract repair: per-row fault isolation ----------

CAP2 = "2026-10-22T18:00:00-05:00"
KO2 = "2026-10-22T19:20:00-05:00"


def _wr_season():
    def row(tgt, rec):
        return {"attempts": 0.0, "passing_yards": 0.0, "carries": 0.0,
                "rushing_yards": 0.0, "targets": tgt, "receptions": rec,
                "receiving_yards": rec * 10.0}
    return {2026: {"WR1": [(w, "WR", row(t, r)) for w, t, r in
                           [(1, 6.0, 5.0), (2, 7.0, 6.0), (3, 6.0, 5.0), (4, 8.0, 6.0)]]}}


def _cap2(rows):
    base = {"game_id": "G1", "captured_at": CAP2, "kickoff": KO2,
            "over_price": -110, "under_price": -110}
    return {"season": 2026, "week": 5, "rows": [dict(base, **r) for r in rows]}


CVS2 = {m: 0.35 for m in EV.MARKETS}
REC = {"player_id": "WR1", "market": "RECEPTIONS"}


def test_count_line_above_grid_refused_not_crash():
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([dict(REC, line=705.5)]), CVS2)
    assert rows[0]["status"] == "REFUSED" and rows[0]["reason"] == "LINE_ABOVE_GRID"
    assert rows[0]["row_id"] == "G1|WR1|RECEPTIONS|705.5"


def test_count_line_below_grid_prices_exactly_one():
    # B2: the negative-index wrap priced this 0.0; the true P(over) is 1.0.
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([dict(REC, line=-61.5)]), CVS2)
    assert rows[0]["status"] == "PRICED" and rows[0]["p_over"] == 1.0


def test_zero_price_row_refused_and_slate_survives():
    qb = {"player_id": "QB1", "market": "PASS_YDS"}
    data = _synthetic_season([(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)])
    cap = _cap2([dict(qb, line=232.5), dict(qb, line=240.5, over_price=0),
                 dict(qb, line=250.5)])
    rows, _ = pricing.price_rows(EV, data, cap, CVS2)
    assert [r["status"] for r in rows] == ["PRICED", "REFUSED", "PRICED"]
    assert rows[1]["reason"] == "ZERO_PRICE_OVER_PRICE"


def test_foreign_market_refused_per_row():
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([
        {"player_id": "WR1", "market": "PASS_TDS", "line": 1.5}]), CVS2)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "MARKET_OUT_OF_SCOPE"


def test_naive_timestamp_refused_not_assumed():
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([
        dict(REC, line=5.5, captured_at="2026-10-22T18:00:00")]), CVS2)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "NAIVE_TIMESTAMP_CAPTURED_AT"


def test_nan_line_refused_and_no_nan_committed():
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([
        dict(REC, line=float("nan"))]), CVS2)
    assert rows[0]["status"] == "REFUSED" and rows[0]["reason"] == "NON_FINITE_LINE"
    assert json.loads(json.dumps({"rows": rows}, allow_nan=False))  # strict JSON


def test_missing_kickoff_refused():
    cap = {"season": 2026, "week": 5, "rows": [
        {"game_id": "G1", "player_id": "WR1", "market": "RECEPTIONS", "line": 5.5,
         "over_price": -110, "under_price": -110, "captured_at": CAP2}]}
    rows, _ = pricing.price_rows(EV, _wr_season(), cap, CVS2)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "MISSING_FIELD_KICKOFF"


def test_negative_yardage_line_refused():
    data = _synthetic_season([(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)])
    rows, _ = pricing.price_rows(EV, data, _cap2([
        {"player_id": "QB1", "market": "PASS_YDS", "line": -3.5}]), CVS2)
    assert rows[0]["status"] == "REFUSED" and rows[0]["reason"] == "NEGATIVE_LINE"


def test_duplicate_row_refused_first_kept():
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([
        dict(REC, line=5.5), dict(REC, line=5.5)]), CVS2)
    assert [r["status"] for r in rows] == ["PRICED", "REFUSED"]
    assert rows[1]["reason"] == "DUPLICATE_ROW"
    assert rows[0]["row_id"] == rows[1]["row_id"]


# ---------- (h) owner acceptance repair: model failures abort, input faults isolate ----------

def test_model_build_failure_aborts_not_refused(monkeypatch):
    # PR #2759 acceptance finding: an evaluator build failure is a
    # systemic failure, not a malformed capture. It must propagate out
    # of price_rows — never become a REFUSED row on a "completed" run.
    def boom(data_by_season, cfg):
        raise RuntimeError("evaluator build exploded")
    monkeypatch.setattr(EV, "build", boom)
    data = _synthetic_season([(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)])
    cap = _cap2([{"player_id": "QB1", "market": "PASS_YDS", "line": 232.5}])
    with pytest.raises(RuntimeError, match="evaluator build exploded"):
        pricing.price_rows(EV, data, cap, CVS2)


def test_scoring_stage_failure_aborts_not_refused(monkeypatch):
    # A failure after the build (here mu_for, the probability stage)
    # aborts the same way — the abort is not specific to ev.build.
    def boom(prior_values, pool):
        raise RuntimeError("mu_for exploded")
    monkeypatch.setattr(EV, "mu_for", boom)
    data = _synthetic_season([(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)])
    cap = _cap2([{"player_id": "QB1", "market": "PASS_YDS", "line": 232.5}])
    with pytest.raises(RuntimeError, match="mu_for exploded"):
        pricing.price_rows(EV, data, cap, CVS2)


def test_cmd_price_model_failure_aborts_and_commits_nothing(tmp_path, monkeypatch):
    # End to end through cmd_price with the evaluator stubbed so the
    # build fails inside the row loop (train_cv is stubbed to succeed):
    # the run aborts and no run_record / priced_rows / pools is written.
    import types

    def boom(data_by_season, cfg):
        raise RuntimeError("evaluator build exploded")

    stub = types.SimpleNamespace(
        MARKETS=EV.MARKETS, K=EV.K, TRAIN=EV.TRAIN,
        GRID_LO=EV.GRID_LO, GRID_HI=EV.GRID_HI,
        build=boom, league_pool=EV.league_pool, mu_for=EV.mu_for,
        candidate_cdf=EV.candidate_cdf,
        load=lambda data_dir: _synthetic_season(
            [(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)]))
    monkeypatch.setattr(pricing, "load_evaluator", lambda: stub)
    monkeypatch.setattr(pricing, "check_training_pins", lambda data: {})
    monkeypatch.setattr(pricing, "train_cv", lambda ev, data, cfg: 0.35)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sp_2026.csv.gz").write_bytes(b"placeholder")
    capture = {"season": 2026, "week": 5, "rows": [
        {"game_id": "G1", "player_id": "QB1", "player_name": "QB One",
         "market": "PASS_YDS", "line": 232.5, "over_price": -112,
         "under_price": -108, "captured_at": CAP2, "kickoff": KO2}]}
    cap_path = tmp_path / "capture.json"
    cap_path.write_text(json.dumps(capture))
    out_dir = tmp_path / "out"
    args = types.SimpleNamespace(player_data=str(data_dir),
                                 capture=str(cap_path),
                                 out_dir=str(out_dir))
    with pytest.raises(RuntimeError, match="evaluator build exploded"):
        pricing.cmd_price(args)
    assert not (out_dir / "run_record.json").exists()
    assert not (out_dir / "priced_rows.json").exists()
    assert not (out_dir / "pools.json").exists()


def test_malformed_row_between_valid_rows_still_isolated():
    # The other half of the distinction: a malformed capture row between
    # two valid rows is still refused per-row and the slate still prices.
    data = _synthetic_season([(1, 200.0), (2, 220.0), (3, 240.0), (4, 260.0)])
    good = {"game_id": "G1", "player_id": "QB1", "market": "PASS_YDS",
            "over_price": -110, "under_price": -110,
            "captured_at": CAP2, "kickoff": KO2}
    bad = {"game_id": "G1", "player_id": "QB1", "market": "PASS_YDS",
           "line": 240.5, "over_price": -110, "under_price": -110,
           "captured_at": CAP2}  # no kickoff: malformed capture input
    capture = {"season": 2026, "week": 5, "rows": [
        dict(good, line=232.5), bad, dict(good, line=250.5)]}
    rows, _ = pricing.price_rows(EV, data, capture, CVS2)
    assert [r["status"] for r in rows] == ["PRICED", "REFUSED", "PRICED"]
    assert rows[1]["reason"] == "MISSING_FIELD_KICKOFF"


def test_nonstring_market_refused_not_crash():
    rows, _ = pricing.price_rows(EV, _wr_season(), _cap2([
        {"player_id": "WR1", "market": ["RECEPTIONS"], "line": 5.5}]), CVS2)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "INVALID_MARKET"
