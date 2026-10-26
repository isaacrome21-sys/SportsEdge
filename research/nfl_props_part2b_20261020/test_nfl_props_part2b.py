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


# ---------- (g) capture-contract repair: per-row fault isolation ----------

RUSH_ATT = {"player_id": "RB1", "market": "RUSH_ATTEMPTS"}
PASS_ATT = {"player_id": "QB1", "market": "PASS_ATTEMPTS"}


def test_count_line_above_grid_refused_not_crash():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        dict(RUSH_ATT, line=705.5)]), CVS)
    assert rows[0]["status"] == "REFUSED" and rows[0]["reason"] == "LINE_ABOVE_GRID"
    assert rows[0]["row_id"] == "G1|RB1|RUSH_ATTEMPTS|705.5"


def test_count_line_below_grid_prices_exactly_one():
    # B2: the negative-index wrap priced this 0.0; the true P(over) is 1.0.
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        dict(RUSH_ATT, line=-61.5)]), CVS)
    assert rows[0]["status"] == "PRICED" and rows[0]["p_over"] == 1.0


def test_zero_price_row_refused_and_slate_survives():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        dict(PASS_ATT, line=33.5), dict(PASS_ATT, line=34.5, over_price=0),
        dict(PASS_ATT, line=35.5)]), CVS)
    assert [r["status"] for r in rows] == ["PRICED", "REFUSED", "PRICED"]
    assert rows[1]["reason"] == "ZERO_PRICE_OVER_PRICE"


def test_naive_timestamp_refused_not_assumed():
    cap = _capture([dict(PASS_ATT, line=33.5)])
    cap["rows"][0]["captured_at"] = "2026-10-22T18:00:00"  # no offset
    rows, _ = pricing.price_rows(EV, _synthetic_data(), cap, CVS)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "NAIVE_TIMESTAMP_CAPTURED_AT"


def test_nan_line_refused_and_no_nan_committed():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        dict(PASS_ATT, line=float("nan"))]), CVS)
    assert rows[0]["status"] == "REFUSED" and rows[0]["reason"] == "NON_FINITE_LINE"
    assert json.loads(json.dumps({"rows": rows}, allow_nan=False))  # strict JSON


def test_missing_kickoff_refused():
    cap = _capture([dict(PASS_ATT, line=33.5)])
    del cap["rows"][0]["kickoff"]
    rows, _ = pricing.price_rows(EV, _synthetic_data(), cap, CVS)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "MISSING_FIELD_KICKOFF"


def test_duplicate_row_refused_first_kept():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        dict(PASS_ATT, line=33.5), dict(PASS_ATT, line=33.5)]), CVS)
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
    cap = _capture([dict(PASS_ATT, line=33.5)])
    with pytest.raises(RuntimeError, match="evaluator build exploded"):
        pricing.price_rows(EV, _synthetic_data(), cap, CVS)


def test_scoring_stage_failure_aborts_not_refused(monkeypatch):
    # A failure after the build (here mu_for, the probability stage)
    # aborts the same way — the abort is not specific to ev.build.
    def boom(prior_values, pool):
        raise RuntimeError("mu_for exploded")
    monkeypatch.setattr(EV, "mu_for", boom)
    cap = _capture([dict(PASS_ATT, line=33.5)])
    with pytest.raises(RuntimeError, match="mu_for exploded"):
        pricing.price_rows(EV, _synthetic_data(), cap, CVS)


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
        load=lambda data_dir: _synthetic_data())
    monkeypatch.setattr(pricing, "load_evaluator", lambda: stub)
    monkeypatch.setattr(pricing, "check_training_pins", lambda data: {})
    monkeypatch.setattr(pricing, "check_b8_active_runtime", lambda data, ev: {})
    monkeypatch.setattr(pricing, "train_cv", lambda ev, data, cfg: 0.30)
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "sp_2026.csv.gz").write_bytes(b"placeholder")
    capture = {"season": 2026, "week": 5, "rows": [
        {"game_id": "G1", "player_id": "QB1", "player_name": "QB One",
         "market": "PASS_ATTEMPTS", "line": 33.5, "over_price": -110,
         "under_price": -110, "captured_at": CAP_AT, "kickoff": KO}]}
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
    good = {"game_id": "G1", "player_id": "QB1", "market": "PASS_ATTEMPTS",
            "over_price": -110, "under_price": -110,
            "captured_at": CAP_AT, "kickoff": KO}
    bad = {"game_id": "G1", "player_id": "QB1", "market": "PASS_ATTEMPTS",
           "line": 34.5, "over_price": -110, "under_price": -110,
           "captured_at": CAP_AT}  # no kickoff: malformed capture input
    capture = {"season": 2026, "week": 5, "rows": [
        dict(good, line=33.5), bad, dict(good, line=35.5)]}
    rows, _ = pricing.price_rows(EV, _synthetic_data(), capture, CVS)
    assert [r["status"] for r in rows] == ["PRICED", "REFUSED", "PRICED"]
    assert rows[1]["reason"] == "MISSING_FIELD_KICKOFF"


def test_nonstring_market_refused_not_crash():
    rows, _ = pricing.price_rows(EV, _synthetic_data(), _capture([
        {"player_id": "RB1", "market": ["RUSH_ATTEMPTS"], "line": 12.5}]), CVS)
    assert rows[0]["status"] == "REFUSED"
    assert rows[0]["reason"] == "INVALID_MARKET"


# ---------- (e) B8 re-pin: sp_2025 played-game correction ----------
# AMENDMENT_B8_SP2025_REPIN_20261026.md. Same drift, same corrected
# artifact, same pin as Part 2: the as-published sp_2025.csv.gz carries
# zero-usage roster rows the frozen loader counts as played games. The
# re-pin replaces that one SPEC_HASHES line; no code, evaluator or other
# pin changes. The generator lives in the Part 2 package (the artifact is
# shared, as the original file and its pin were).

import importlib.util as _ilu  # noqa: E402

_b8_spec = _ilu.spec_from_file_location(
    "build_sp_2025_played_v2",
    HERE.parent / "nfl_props_part2_20261018" / "build_sp_2025_played_v2.py")
b8gen = _ilu.module_from_spec(_b8_spec)
_b8_spec.loader.exec_module(b8gen)

B8_ORIGINAL_SP_2025_SHA256 = "c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b"
B8_CORRECTED_NAME = "sp_2025_played_v2.csv.gz"
B8_CORRECTED_SHA256 = "f2768ac1c71e5ed616307106df32ef8ad4fc7d548bb96600f6a616fb631f7b48"
B8_FROZEN_OTHER_PINS = {
    "PREREG_NFL_PROPS_PART2B_FORWARD_V1.md":
        "55e11a818329d91d379dad88604c6e9fb66b61a57903ed98bc88ded5dcaebb2e",
    "ps_2018.csv.gz": "15730d75271ec10affc412b50b22fc8e3d6ce8f442d377936f65bc0044ef15bf",
    "ps_2019.csv.gz": "d143b91c62380bed1587fe390e594d0e5555e8ebac81fcc7212ad7224115caf2",
    "ps_2020.csv.gz": "e23a81d6ed3c94bd2dd14a5ee3ed94584a69e67fdb985c1ba0de4ccbc5a2bdcc",
    "ps_2021.csv.gz": "a2fb266576a1bde5d7978005a5f6ccf83e3c023234da500d38cf6a14f40a01c8",
    "ps_2022.csv.gz": "2b7dca6814993b9fd6ad3d4fdc56131663311bbe83281126e1ac441620d824ba",
    "ps_2023.csv.gz": "b7590543f3c81dceb17d7577a1dce7b8ff1a9aacf0f562e3d7bbc7e60f37bc9b",
    "ps_2024.csv.gz": "629b77e0c88d361f8b5c4a850e7866013aa670b7a5a94b7f1d0c591adf18f971",
}


def _spec_hashes() -> dict:
    want = {}
    for line in (HERE / "SPEC_HASHES.txt").read_text().splitlines():
        h, name = line.split()
        want[name] = h
    return want


def test_b8_repin_spec_hashes_registry():
    want = _spec_hashes()
    assert "sp_2025.csv.gz" not in want
    assert want[B8_CORRECTED_NAME] == B8_CORRECTED_SHA256
    assert B8_CORRECTED_SHA256 != B8_ORIGINAL_SP_2025_SHA256
    for name, h in B8_FROZEN_OTHER_PINS.items():
        assert want[name] == h, name
    assert set(want) == set(B8_FROZEN_OTHER_PINS) | {B8_CORRECTED_NAME}


def test_b8_runtime_gate_rejects_mixed_2025_and_never_loads(tmp_path, monkeypatch):
    import types

    calls = []
    ev = types.SimpleNamespace(
        check_hashes=lambda directory: calls.append("hash") or {},
        load=lambda directory: calls.append("load"),
    )
    monkeypatch.setattr(pricing, "load_evaluator", lambda: ev)
    monkeypatch.setattr(pricing, "check_training_pins", lambda directory: {})
    (tmp_path / "sp_2025_played_v2.csv.gz").write_bytes(b"corrected fixture")
    (tmp_path / "sp_2025.csv.gz").write_bytes(b"legacy fixture")
    output = tmp_path / "should_not_exist"
    args = types.SimpleNamespace(
        player_data=str(tmp_path), capture=str(tmp_path / "missing.json"),
        out_dir=str(output),
    )
    with pytest.raises(SystemExit, match="B8_RUNTIME_LEGACY_2025_FILE_FORBIDDEN"):
        pricing.cmd_price(args)
    assert calls == []
    assert not output.exists()


def test_b8_repin_leaves_evaluator_pin_untouched():
    digest = hashlib.sha256((HERE / pricing.EVALUATOR_NAME).read_bytes()).hexdigest()
    assert digest == pricing.EVALUATOR_SHA256 == \
        "a941164e10a66dd079daaed1593387987035a59a92a8b15d94d0366fa3e82417"


_B8_HEADER = ["player_id", "player_name", "position", "season", "week",
              "season_type", "attempts", "passing_yards", "passing_tds",
              "completions", "carries", "rushing_yards", "targets",
              "receptions", "receiving_yards"]


def _b8_row(pid, pos, week, st="REG", att=0, py=0, ptd=0, comp=0, car=0,
            ry=0, tar=0, rec=0, recy=0):
    return [pid, pid, pos, 2025, week, st, att, py, ptd, comp, car, ry,
            tar, rec, recy]


def _b8_write_gz(path, rows):
    import csv
    import gzip
    import io
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(_B8_HEADER)
    w.writerows(rows)
    path.write_bytes(gzip.compress(buf.getvalue().encode(), mtime=0))


def test_b8_played_filter_excludes_phantom_weeks(tmp_path):
    rows = [_b8_row("00-QB-POOL", "QB", w, att=33, py=250, ptd=2, comp=22)
            for w in range(1, 7)]
    rows += [_b8_row("00-QB-PHANTOM", "QB", w) for w in (1, 2, 3)]
    rows += [_b8_row("00-QB-PHANTOM", "QB", 4, att=42, py=290, ptd=3, comp=27),
             _b8_row("00-QB-PHANTOM", "QB", 5, att=44, py=301, ptd=2, comp=29),
             _b8_row("00-QB-PHANTOM", "QB", 6, att=40, py=262, ptd=2, comp=25),
             _b8_row("00-QB-PHANTOM", "QB", 19, st="POST")]
    rows += [_b8_row("00-K-REAL", "K", w) for w in (1, 2, 3)]
    rows += [_b8_row("00-LB-REAL", "LB", w) for w in (1, 2)]
    src = tmp_path / "sp_2025.csv.gz"
    _b8_write_gz(src, rows)
    payload, counts = b8gen.build_corrected(src)
    assert counts["source_rows"] == 18
    assert counts["removed_by_type"] == {"REG": 3, "POST": 1, "other": 0}
    assert counts["kept_rows"] == 14
    payload2, _ = b8gen.build_corrected(src)
    assert payload2 == payload

    corr_dir = tmp_path / "corr"
    corr_dir.mkdir()
    (corr_dir / B8_CORRECTED_NAME).write_bytes(payload)
    orig_dir = tmp_path / "orig"
    orig_dir.mkdir()
    (orig_dir / "sp_2025.csv.gz").write_bytes(src.read_bytes())

    corr = EV.load(corr_dir)[2025]
    orig = EV.load(orig_dir)[2025]
    assert [g[0] for g in corr["00-QB-PHANTOM"]] == [4, 5, 6]
    assert [g[0] for g in orig["00-QB-PHANTOM"]] == [1, 2, 3, 4, 5, 6]
    assert [g[0] for g in corr["00-K-REAL"]] == [1, 2, 3]
    assert [g[0] for g in corr["00-LB-REAL"]] == [1, 2]

    # PASS_ATTEMPTS at week 7: prices in both worlds, but under the
    # corrected artifact the priors are the 3 played games only (pool is
    # the pool QB's [33, 33, 33] in both runs)
    capture = {"season": 2025, "week": 7, "rows": [
        {"game_id": "G1", "player_id": "00-QB-PHANTOM", "market": "PASS_ATTEMPTS",
         "line": 31.5, "over_price": -110, "under_price": -110,
         "captured_at": "2025-10-20T18:00:00-05:00",
         "kickoff": "2025-10-20T19:20:00-05:00"}]}
    cvs = {m: 0.35 for m in EV.MARKETS}
    rows_o, _ = pricing.price_rows(EV, EV.load(orig_dir), capture, cvs)
    rows_c, _ = pricing.price_rows(EV, EV.load(corr_dir), capture, cvs)
    assert rows_o[0]["status"] == rows_c[0]["status"] == "PRICED"
    assert rows_o[0]["games_logged"] == 6
    assert rows_o[0]["prior_values"] == [0.0, 0.0, 0.0, 42.0, 44.0, 40.0]
    assert rows_o[0]["mu"] == pytest.approx((126.0 + 99.0) / 9.0)
    assert rows_c[0]["games_logged"] == 3
    assert rows_c[0]["prior_values"] == [42.0, 44.0, 40.0]
    assert rows_c[0]["mu"] == pytest.approx((126.0 + 99.0) / 6.0)

    cap4 = dict(capture, week=4)
    rows_o4, _ = pricing.price_rows(EV, EV.load(orig_dir), cap4, cvs)
    rows_c4, _ = pricing.price_rows(EV, EV.load(corr_dir), cap4, cvs)
    assert rows_o4[0]["status"] == "NOT_QUALIFIED"
    assert rows_o4[0]["reason"].startswith("ROLE_MEAN")
    assert rows_o4[0]["games_logged"] == 3
    assert rows_c4[0]["status"] == "NOT_QUALIFIED"
    assert rows_c4[0]["reason"] == "ONLY_0_PRIOR_GAMES"
    assert rows_c4[0]["games_logged"] == 0


def test_b8_staged_artifact_matches_pin():
    """Skip-if-absent mirror of the Part 2 staged-artifact test, under
    the 2B evaluator's own loader and hash check."""
    import os
    data_dir = Path(os.environ.get(
        "NFL_PROPS_DATA_DIR",
        Path.home() / "workspace/sportsedge/nfl_player_data_repin_20261026"))
    artifact = data_dir / B8_CORRECTED_NAME
    if not artifact.exists():
        pytest.skip("re-pin staging data dir not present on this machine")
    assert not (data_dir / "sp_2025.csv.gz").exists()  # never both files
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert digest == _spec_hashes()[B8_CORRECTED_NAME] == B8_CORRECTED_SHA256
    EV.check_hashes(data_dir)  # raises SystemExit on any pin mismatch
    season = EV.load(data_dir)[2025]
    affected = 0
    for pid, games in season.items():
        for w, pos, row in games:
            usage = row["attempts"] + row["carries"] + row["targets"]
            assert not (pos in b8gen.SKILL_POSITIONS and usage == 0.0), pid
        if games[-1][1] not in b8gen.SKILL_POSITIONS:
            continue
        for i in range(len(games)):
            priors = games[:i]
            played = [g for g in priors
                      if g[2]["attempts"] + g[2]["carries"] + g[2]["targets"] > 0]
            if len(priors) >= 3 and len(played) < 3:
                affected += 1
    assert affected == 0
