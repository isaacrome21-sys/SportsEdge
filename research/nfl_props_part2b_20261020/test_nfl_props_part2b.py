"""Part 2B forward-test package tests (PREREG_NFL_PROPS_PART2B_FORWARD_V1).

Run: python3 -m pytest research/nfl_props_part2b_20261020/test_nfl_props_part2b.py
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

import price_nfl_props_part2b as pricing  # noqa: E402
import score_nfl_props_part2b as scoring  # noqa: E402

EV = pricing.load_evaluator()
GRID = np.arange(EV.GRID_LO, EV.GRID_HI + 1, dtype=float)
CAP_AT = "2026-10-22T18:00:00-05:00"
KO = "2026-10-22T19:20:00-05:00"


# ---------- (a) pins and construction identity with Part 1 ----------

def test_evaluator_file_matches_pinned_hash():
    digest = hashlib.sha256((HERE / pricing.EVALUATOR_NAME).read_bytes()).hexdigest()
    assert digest == pricing.EVALUATOR_SHA256
    assert digest == "a941164e10a66dd079daaed1593387987035a59a92a8b15d94d0366fa3e82417"


def test_part1_evaluator_untouched_by_2b():
    part1 = HERE.parent / "nfl_props_part2_20261018" / "eval_nfl_props_calibration_v1.py"
    digest = hashlib.sha256(part1.read_bytes()).hexdigest()
    assert digest == "66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b"


def test_construction_constants_and_markets():
    assert EV.K == 3.0
    assert EV.TRAIN == (2018, 2019)
    assert set(EV.MARKETS) == {"RUSH_ATTEMPTS", "PASS_ATTEMPTS", "COMPLETIONS", "PASS_TDS"}
    assert all(cfg["count"] for cfg in EV.MARKETS.values())
    assert EV.MARKETS["PASS_TDS"].get("shadow") is True
    assert not any(cfg.get("shadow") for m, cfg in EV.MARKETS.items() if m != "PASS_TDS")
    # Role gates reuse the frozen markets' populations (Part 2B §1).
    assert EV.MARKETS["PASS_ATTEMPTS"]["role"] == "attempts"
    assert EV.MARKETS["PASS_ATTEMPTS"]["thr"] == 20.0
    assert EV.MARKETS["COMPLETIONS"]["role"] == "attempts"
    assert EV.MARKETS["RUSH_ATTEMPTS"]["role"] == "carries"
    assert EV.MARKETS["RUSH_ATTEMPTS"]["thr"] == 8.0


def test_mu_for_hand_computed():
    # Same arithmetic as Part 1: (sum(prior) + K*pool_mean) / (n + K).
    assert EV.mu_for([30.0, 32.0, 34.0, 36.0], [36.0]) == pytest.approx(240.0 / 7.0)


def test_count_cdf_matches_scipy_negbin():
    mu, cv = 33.0, 0.30
    cdf = EV.candidate_cdf(mu, cv, True, GRID)
    var = (cv * mu) ** 2
    r = mu * mu / (var - mu)
    assert cdf[33 - EV.GRID_LO] == pytest.approx(
        stats.nbinom.cdf(33, r, r / (r + mu)), abs=1e-12)


def test_p_over_count_uses_floor_rule():
    # For a counting stat, P(Y > 33.5) = 1 - CDF(33) (the evaluator's rule).
    mu, cv = 33.0, 0.30
    p = pricing.p_over_for(EV, mu, cv, True, 33.5, GRID)
    cdf = EV.candidate_cdf(mu, cv, True, GRID)
    assert p == pytest.approx(1.0 - float(cdf[33 - EV.GRID_LO]))
    assert 0.0 < p < 1.0


# ---------- (b) pricing: distributions, PIT, qualification, labels ----------

def _row(att, comp, tds, car):
    return {"attempts": att, "completions": comp, "passing_tds": tds,
            "passing_yards": att * 7.0, "carries": car, "rushing_yards": car * 4.0,
            "targets": 0.0, "receptions": 0.0, "receiving_yards": 0.0}


def _synthetic_data(extra_qb_games=()):
    qb = [(w, "QB", _row(a, a * 0.62, 2.0, 3.0))
          for w, a in [(1, 30.0), (2, 32.0), (3, 34.0), (4, 36.0)]]
    qb += list(extra_qb_games)
    rb = [(w, "RB", _row(0.0, 0.0, 0.0, c))
          for w, c in [(1, 10.0), (2, 12.0), (3, 14.0), (4, 16.0)]]
    low = [(w, "RB", _row(0.0, 0.0, 0.0, c))
           for w, c in [(1, 2.0), (2, 3.0), (3, 2.0), (4, 3.0)]]
    return {2026: {"QB1": qb, "RB1": rb, "RB_LOW": low}}


def _capture(rows):
    base = {"game_id": "G1", "captured_at": CAP_AT, "kickoff": KO,
            "over_price": -110, "under_price": -110}
    return {"season": 2026, "week": 5,
            "rows": [dict(base, **r) for r in rows]}


CVS = {m: 0.30 for m in EV.MARKETS}


def test_price_all_2b_markets_with_hand_checked_mus():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        {"player_id": "QB1", "market": "PASS_ATTEMPTS", "line": 33.5},
        {"player_id": "QB1", "market": "COMPLETIONS", "line": 21.5},
        {"player_id": "QB1", "market": "PASS_TDS", "line": 1.5},
        {"player_id": "RB1", "market": "RUSH_ATTEMPTS", "line": 12.5},
    ]), CVS)
    by_market = {r["market"]: r for r in rows}
    assert all(r["status"] == "PRICED" for r in rows)
    # Pool for each market is the single qualified outcome before week 5
    # (the week-4 value): PASS_ATTEMPTS mu = (132 + 3*36)/7.
    assert by_market["PASS_ATTEMPTS"]["mu"] == pytest.approx(240.0 / 7.0)
    assert by_market["RUSH_ATTEMPTS"]["mu"] == pytest.approx((52.0 + 48.0) / 7.0)
    assert by_market["PASS_TDS"]["mu"] == pytest.approx(2.0)
    for r in rows:
        assert 0.0 < r["p_over"] < 1.0
        assert r["p_over"] + r["p_under"] == pytest.approx(1.0)


def test_shadow_label_and_warning_annotation():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        {"player_id": "QB1", "market": "PASS_ATTEMPTS", "line": 33.5},
        {"player_id": "QB1", "market": "COMPLETIONS", "line": 21.5},
        {"player_id": "QB1", "market": "PASS_TDS", "line": 1.5},
        {"player_id": "RB1", "market": "RUSH_ATTEMPTS", "line": 12.5},
    ]), CVS)
    by_market = {r["market"]: r for r in rows}
    assert by_market["PASS_TDS"]["label"] == "SHADOW"
    assert all(by_market[m]["label"] == "FORWARD_TEST"
               for m in ("PASS_ATTEMPTS", "COMPLETIONS", "RUSH_ATTEMPTS"))
    # §3 annotation rides on the QB volume markets only.
    assert "warning" in by_market["PASS_ATTEMPTS"]
    assert "warning" in by_market["COMPLETIONS"]
    assert "warning" not in by_market["RUSH_ATTEMPTS"]
    assert "warning" not in by_market["PASS_TDS"]


def test_pit_exclusion_future_games_do_not_move_mu():
    monster = [(5, "QB", _row(99.0, 90.0, 9.0, 3.0)),
               (6, "QB", _row(99.0, 90.0, 9.0, 3.0))]
    cap = _capture([{"player_id": "QB1", "market": "PASS_ATTEMPTS", "line": 33.5}])
    base_rows, _ = pricing.price_rows(EV, _synthetic_data(), cap, CVS)
    fut_rows, _ = pricing.price_rows(EV, _synthetic_data(monster), cap, CVS)
    assert fut_rows[0]["mu"] == pytest.approx(base_rows[0]["mu"])
    assert fut_rows[0]["p_over"] == pytest.approx(base_rows[0]["p_over"])
    assert fut_rows[0]["games_logged"] == 4


def test_qualification_gates_apply():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        {"player_id": "RB_LOW", "market": "RUSH_ATTEMPTS", "line": 4.5},
        {"player_id": "RB1", "market": "PASS_ATTEMPTS", "line": 33.5},
        {"player_id": "GHOST", "market": "COMPLETIONS", "line": 21.5},
    ]), CVS)
    by_pid = {r["player_id"]: r for r in rows}
    assert by_pid["RB_LOW"]["status"] == "NOT_QUALIFIED"
    assert "ROLE_MEAN" in by_pid["RB_LOW"]["reason"]
    assert by_pid["RB1"]["status"] == "NOT_QUALIFIED"
    assert by_pid["RB1"]["reason"] == "NOT_QB"
    assert by_pid["GHOST"]["reason"] == "ONLY_0_PRIOR_GAMES"


def test_interceptions_refused_fail_closed():
    with pytest.raises(SystemExit) as exc:
        pricing.price_rows(EV, _synthetic_data(), _capture([
            {"player_id": "QB1", "market": "INTERCEPTIONS", "line": 0.5},
        ]), CVS)
    assert "MARKET_OUT_OF_SCOPE_2B" in str(exc.value)


def test_late_capture_excluded():
    cap = _capture([{"player_id": "QB1", "market": "PASS_ATTEMPTS", "line": 33.5}])
    cap["rows"][0]["captured_at"] = KO  # at kickoff: not pre-kickoff
    rows, _ = pricing.price_rows(EV, _synthetic_data(), cap, CVS)
    assert rows[0]["status"] == "EXCLUDED_LATE_CAPTURE"


# ---------- (c) close attachment parity with Part 2 ----------

def test_missing_close_is_clv_missing_no_close_row(tmp_path):
    rows, pools = pricing.price_rows(EV, _synthetic_data(), _capture([
        {"player_id": "QB1", "market": "PASS_ATTEMPTS", "line": 33.5},
    ]), CVS)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "priced_rows.json").write_text(json.dumps({"run": {}, "rows": rows}))
    (run_dir / "pools.json").write_text(json.dumps(pools))
    close = {"season": 2026, "week": 5, "rows": []}
    close_path = tmp_path / "close.json"
    close_path.write_text(json.dumps(close))
    summary = pricing.attach_close(run_dir, close_path)
    assert summary == {"readable": 0, "clv_missing": 1}
    after = json.loads((run_dir / "priced_rows.json").read_text())["rows"][0]
    assert after["close_status"] == "CLV_MISSING"
    assert after["clv_missing_reason"] == "NO_CLOSE_ROW"


# ---------- (d) verdict gates: §4 as ruled 2026-10-20 (option (a)) ----------

def test_verdict_gates_have_no_50_row_market_gate():
    # 100+ rows, 4 slates, 40 games, clean closes, positive game-clustered
    # CI: BEATS_MARKET with NO passing-yards-style row condition anywhere.
    v, note = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=40,
        clv_missing_share=0.0, clv_ci_lo_game=0.01, clv_ci_lo_qb=None)
    assert v == "BEATS_MARKET" and note is None


def test_verdict_gates_order():
    v, _ = scoring.market_verdict(
        slates_completed=4, graded_rows=99, distinct_games=40,
        clv_missing_share=0.0, clv_ci_lo_game=0.01, clv_ci_lo_qb=None)
    assert v == "INSUFFICIENT_SAMPLE"
    v, _ = scoring.market_verdict(
        slates_completed=3, graded_rows=150, distinct_games=40,
        clv_missing_share=0.0, clv_ci_lo_game=0.01, clv_ci_lo_qb=None)
    assert v == "REVIEW_NOT_OPEN"
    v, _ = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=39,
        clv_missing_share=0.0, clv_ci_lo_game=0.01, clv_ci_lo_qb=None)
    assert v == "REVIEW_NOT_OPEN"
    v, _ = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=40,
        clv_missing_share=0.21, clv_ci_lo_game=0.01, clv_ci_lo_qb=None)
    assert v == "INSUFFICIENT_CLOSE_DATA"
    v, _ = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=40,
        clv_missing_share=0.20, clv_ci_lo_game=0.01, clv_ci_lo_qb=None)
    assert v == "BEATS_MARKET"  # exactly 20% missing still allows a verdict
    v, _ = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=40,
        clv_missing_share=0.0, clv_ci_lo_game=-0.01, clv_ci_lo_qb=None)
    assert v == "DOES_NOT_BEAT_MARKET"


def test_qb_cluster_disagreement_weakens_verdict():
    v, note = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=40,
        clv_missing_share=0.0, clv_ci_lo_game=0.01, clv_ci_lo_qb=-0.005)
    assert v == "DOES_NOT_BEAT_MARKET"
    assert note is not None and "QB_CLUSTERED" in note
    v, note = scoring.market_verdict(
        slates_completed=4, graded_rows=150, distinct_games=40,
        clv_missing_share=0.0, clv_ci_lo_game=0.01, clv_ci_lo_qb=0.002)
    assert v == "BEATS_MARKET" and note is None


# ---------- (e) scorer: SHADOW never enters an aggregate ----------

def test_shadow_rows_scored_for_record_only(tmp_path):
    rows, pools = pricing.price_rows(EV, _synthetic_data(), _capture([
        {"player_id": "QB1", "market": "PASS_ATTEMPTS", "line": 33.5},
        {"player_id": "QB1", "market": "PASS_TDS", "line": 1.5},
    ]), CVS)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "priced_rows.json").write_text(json.dumps({"run": {}, "rows": rows}))
    (run_dir / "pools.json").write_text(json.dumps(pools))
    outcomes = {"results": [
        {"player_id": "QB1", "market": "PASS_ATTEMPTS", "value": 35.0},
        {"player_id": "QB1", "market": "PASS_TDS", "value": 3.0},
    ]}
    scored, notes = scoring.score_runs(EV, [run_dir], outcomes)
    assert [r["market"] for r in scored] == ["PASS_ATTEMPTS"]
    shadow = notes["shadow_rows_scored_for_record"]
    assert len(shadow) == 1
    assert shadow[0]["market"] == "PASS_TDS" and shadow[0]["label"] == "SHADOW"
    assert shadow[0]["realized_value"] == 3.0 and shadow[0]["outcome"] == "OVER"
    agg = scoring.aggregate_market(EV, scored, slates_completed=1)
    assert agg["graded_rows"] == 1  # the shadow row is not counted anywhere


# ---------- (f) the frozen document carries the ruled terms ----------

def test_frozen_prereg_terms_present():
    text = (HERE / "PREREG_NFL_PROPS_PART2B_FORWARD_V1.md").read_text()
    assert "RULED option (a) (Isaac" in text
    assert "2026-10-20" in text
    assert "DRAFT — NOT IN FORCE" not in text
    assert "OPEN items" not in text
    for term in ("RUSH ATTEMPTS", "PASS ATTEMPTS", "COMPLETIONS",
                 "SHADOW-ONLY", "INTERCEPTIONS", "INSUFFICIENT_SAMPLE",
                 "40 distinct games", "100 rows"):
        assert term in text, term
