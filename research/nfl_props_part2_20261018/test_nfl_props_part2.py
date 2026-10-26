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


# ---------- (e) B8 re-pin: sp_2025 played-game correction ----------
# AMENDMENT_B8_SP2025_REPIN_20261026.md. The as-published sp_2025.csv.gz
# carries zero-usage roster rows for players who did not play; the frozen
# loader counts each as a played game (434 skill-player-weeks in 2025 reach
# "3 prior games" with fewer than 3 played). The re-pin replaces that one
# pin with the played-game-filtered artifact; no code, evaluator or other
# pin changes.

import build_sp_2025_played_v2 as b8gen  # noqa: E402

B8_ORIGINAL_SP_2025_SHA256 = "c7401e321bdb369443f3280b9acd74ba6e16d82e710383bf1c01acabfebeac0b"
B8_CORRECTED_NAME = "sp_2025_played_v2.csv.gz"
B8_CORRECTED_SHA256 = "f2768ac1c71e5ed616307106df32ef8ad4fc7d548bb96600f6a616fb631f7b48"
B8_FROZEN_OTHER_PINS = {
    "PREREG_NFL_PROPS_CALIBRATION_V1.md":
        "bef8d74ee1bfd3f1a753872c3e5fe428fbd00b6b98b5b911b4f8324ac1a7a148",
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
    # the drifted artifact's pin is REPLACED, not supplemented: a data dir
    # must never carry both files (the loader globs sp_*.csv.gz)
    assert "sp_2025.csv.gz" not in want
    assert want[B8_CORRECTED_NAME] == B8_CORRECTED_SHA256
    assert B8_CORRECTED_SHA256 != B8_ORIGINAL_SP_2025_SHA256
    # every other pin is the frozen original, byte for byte
    for name, h in B8_FROZEN_OTHER_PINS.items():
        assert want[name] == h, name
    assert set(want) == set(B8_FROZEN_OTHER_PINS) | {B8_CORRECTED_NAME}


def test_b8_repin_leaves_evaluator_pin_untouched():
    # lockstep is via SPEC_HASHES (the registry both the evaluator's
    # check_hashes and this pricer's check_training_pins read); the
    # evaluator file itself — and therefore its prereg pin — is unchanged
    digest = hashlib.sha256((HERE / pricing.EVALUATOR_NAME).read_bytes()).hexdigest()
    assert digest == pricing.EVALUATOR_SHA256 == \
        "66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b"


_B8_HEADER = ["player_id", "player_name", "position", "season", "week",
              "season_type", "attempts", "passing_yards", "passing_tds",
              "completions", "carries", "rushing_yards", "targets",
              "receptions", "receiving_yards"]


def _b8_row(pid, pos, week, st="REG", att=0, py=0, ptd=0, comp=0, car=0,
            ry=0, tar=0, rec=0, recy=0):
    return [pid, pid, pos, 2025, week, st, att, py, ptd, comp, car, ry,
            tar, rec, recy]


def _b8_synthetic_rows():
    rows = [_b8_row("00-WR-POOL", "WR", w, att=0, tar=10, rec=7, recy=90)
            for w in range(1, 7)]
    rows += [_b8_row("00-WR-PHANTOM", "WR", w) for w in (1, 2, 3)]
    rows += [_b8_row("00-WR-PHANTOM", "WR", 4, tar=9, rec=6, recy=72),
             _b8_row("00-WR-PHANTOM", "WR", 5, tar=9, rec=7, recy=81),
             _b8_row("00-WR-PHANTOM", "WR", 6, tar=9, rec=5, recy=64),
             _b8_row("00-WR-PHANTOM", "WR", 19, st="POST")]
    rows += [_b8_row("00-RB-REAL", "RB", 1, car=12, ry=55, tar=2, rec=2, recy=14),
             _b8_row("00-RB-REAL", "RB", 2, car=14, ry=63, tar=3, rec=3, recy=19),
             _b8_row("00-RB-REAL", "RB", 3, car=11, ry=47, tar=1, rec=1, recy=8)]
    rows += [_b8_row("00-K-REAL", "K", w) for w in (1, 2, 3)]
    rows += [_b8_row("00-LB-REAL", "LB", w) for w in (1, 2)]
    return rows


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
    src = tmp_path / "sp_2025.csv.gz"
    _b8_write_gz(src, _b8_synthetic_rows())
    payload, counts = b8gen.build_corrected(src)
    # 21 rows in; exactly the WR's 3 REG + 1 POST phantom rows removed;
    # the kicker's and linebacker's zero-offensive-usage rows are NOT
    # this correction's to delete and survive untouched
    assert counts["source_rows"] == 21
    assert counts["removed_by_type"] == {"REG": 3, "POST": 1, "other": 0}
    assert counts["kept_rows"] == 17
    # deterministic: rebuilding from the same source is byte-identical
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
    assert [g[0] for g in corr["00-WR-PHANTOM"]] == [4, 5, 6]
    assert [g[0] for g in orig["00-WR-PHANTOM"]] == [1, 2, 3, 4, 5, 6]
    assert [g[0] for g in corr["00-K-REAL"]] == [1, 2, 3]
    assert [g[0] for g in corr["00-LB-REAL"]] == [1, 2]
    assert corr["00-RB-REAL"] == orig["00-RB-REAL"]

    # the pricing consequence: at week 7 the phantom WR still prices, but
    # from his 3 played games only — no phantom 0.0s in the priors, and
    # games_logged stops inflating (mu is no longer dragged by 0.0 rows:
    # pool is the pool WR's [90, 90, 90] in both runs)
    capture = {"season": 2025, "week": 7, "rows": [
        {"game_id": "G1", "player_id": "00-WR-PHANTOM", "market": "REC_YDS",
         "line": 55.5, "over_price": -110, "under_price": -110,
         "captured_at": "2025-10-20T18:00:00-05:00",
         "kickoff": "2025-10-20T19:20:00-05:00"}]}
    cvs = {m: 0.35 for m in EV.MARKETS}
    rows_o, _ = pricing.price_rows(EV, EV.load(orig_dir), capture, cvs)
    rows_c, _ = pricing.price_rows(EV, EV.load(corr_dir), capture, cvs)
    assert rows_o[0]["status"] == rows_c[0]["status"] == "PRICED"
    assert rows_o[0]["games_logged"] == 6
    assert rows_o[0]["prior_values"] == [0.0, 0.0, 0.0, 72.0, 81.0, 64.0]
    assert rows_o[0]["mu"] == pytest.approx((217.0 + 270.0) / 9.0)
    assert rows_c[0]["games_logged"] == 3
    assert rows_c[0]["prior_values"] == [72.0, 81.0, 64.0]
    assert rows_c[0]["mu"] == pytest.approx((217.0 + 270.0) / 6.0)

    # and the 434-pattern itself: at week 4 the phantom WR previously
    # reached the 3-prior-game minimum on zero played games (failing only
    # at the role gate); under the corrected artifact he has no priors
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
    """Skip-if-absent: when the re-pin staging data dir is present, the
    artifact on disk must be the pinned one, the evaluator's hash check
    must pass on that dir, and its loaded 2025 season must be phantom-free
    (the S12 affected-weeks measure of the Oct 24 sweep reads 0)."""
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
            continue  # the sweep's measure is over skill players only
        for i in range(len(games)):
            priors = games[:i]
            played = [g for g in priors
                      if g[2]["attempts"] + g[2]["carries"] + g[2]["targets"] > 0]
            if len(priors) >= 3 and len(played) < 3:
                affected += 1
    assert affected == 0
