"""Unit tests for the UFC moneyline Leg 1 design screen helpers.

All fixtures are synthetic; no network and no pinned data files are used.
The screen itself lives in research/ufc_moneyline_screen_20261028/.
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date
from math import log
from pathlib import Path

import pytest

from sportsedge.ufc_training import TrainingRow

_SCREEN_PATH = (
    Path(__file__).resolve().parents[1]
    / "research" / "ufc_moneyline_screen_20261028" / "run_screen.py"
)
_spec = importlib.util.spec_from_file_location("ufc_moneyline_screen", _SCREEN_PATH)
screen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screen)


def _row(day: str, a: str, b: str, y: int, elo_diff: float = 0.0) -> TrainingRow:
    return TrainingRow(
        fight_date=day, event="E", fighter_a=a, fighter_b=b, y_a_win=y,
        features={"elo_diff": elo_diff},
    )


# --------------------------------------------------------------- odds math ----

def test_devig_pair_favorite_underdog():
    pa, pb = screen.devig_pair(-200.0, 170.0)
    assert pa > pb
    assert pa + pb == pytest.approx(1.0)
    # raw implied: 200/300 and 100/270
    assert pa == pytest.approx((200 / 300) / (200 / 300 + 100 / 270))


def test_devig_pair_pickem():
    pa, pb = screen.devig_pair(-110.0, -110.0)
    assert pa == pytest.approx(0.5) and pb == pytest.approx(0.5)


def test_american_profit_per_unit():
    assert screen.american_profit_per_unit(150.0) == pytest.approx(1.5)
    assert screen.american_profit_per_unit(-200.0) == pytest.approx(0.5)


# ---------------------------------------------------------------- metrics ----

def test_probability_metrics_perfect_and_coinflip():
    perfect = screen.probability_metrics([(1.0, 1), (0.0, 0)])
    assert perfect["n"] == 2
    assert perfect["brier"] == pytest.approx(0.0, abs=1e-9)
    assert perfect["accuracy"] == 1.0
    flip = screen.probability_metrics([(0.5, 1), (0.5, 0)])
    assert flip["log_loss"] == pytest.approx(log(2.0))
    assert flip["brier"] == pytest.approx(0.25)


def test_probability_metrics_empty():
    assert screen.probability_metrics([])["n"] == 0


# -------------------------------------------------------------------- join ----

def test_join_key_norm_folds_accents():
    assert screen.join_key_norm("José Aldo") == screen.join_key_norm("Jose Aldo")


def test_load_market_rows_and_join_agreement():
    text = (
        "R_fighter,B_fighter,R_odds,B_odds,date,Winner\n"
        "Alice A,Bob B,-150,130,2024-01-06,Red\n"
        "Carol C,Dan D,120,-140,2024-01-06,Blue\n"
        "Eve E,Frank F,,,,2024-01-06,Red\n"  # unpriced: not indexed
    )
    market = screen.load_market_rows(text)
    assert len(market) == 2

    class _Bundle:
        training_rows = [
            _row("2024-01-06", "Alice A", "Bob B", 1),   # agrees (Red won)
            _row("2024-01-06", "Dan D", "Carol C", 1),   # agrees (Blue = Dan)
            _row("2024-01-06", "Ghost G", "Henry H", 0),  # unjoined
        ]
        metadata = [{}, {}, {}]

    scored, stats = screen.join_rows(_Bundle, market)
    assert stats["joined_priced"] == 2
    assert stats["outcome_agree"] == 2
    assert stats["outcome_disagree"] == 0
    assert stats["unjoined"] == 1
    # Dan D row: fighter_a is Blue at -140 -> heavy favorite probability.
    dan = next(s for s in scored if s["row"].fighter_a == "Dan D")
    assert dan["market_p_a"] > 0.5
    assert dan["fighter_a_odds"] == -140.0


def test_join_excludes_outcome_disagreement():
    text = (
        "R_fighter,B_fighter,R_odds,B_odds,date,Winner\n"
        "Alice A,Bob B,-150,130,2024-01-06,Blue\n"
    )
    market = screen.load_market_rows(text)

    class _Bundle:
        training_rows = [_row("2024-01-06", "Alice A", "Bob B", 1)]  # says A won
        metadata = [{}]

    scored, stats = screen.join_rows(_Bundle, market)
    assert scored == []
    assert stats["outcome_disagree"] == 1


# -------------------------------------------------------------- Elo artifact ----

def test_elo_only_artifact_reproduces_elo_expectation():
    rows = [_row("2019-01-01", "A", "B", 1, elo_diff=100.0),
            _row("2019-01-02", "C", "D", 0, elo_diff=-100.0)]
    artifact = screen.elo_only_artifact(rows)
    p = artifact.raw_probability({"elo_diff": 100.0})
    expected = 1.0 / (1.0 + 10 ** (-100.0 / 400.0))
    assert p == pytest.approx(expected, abs=1e-9)
    p0 = artifact.raw_probability({"elo_diff": 0.0})
    assert p0 == pytest.approx(0.5)


# ------------------------------------------------------------------- gates ----

def _contract():
    return {
        "holdout_n_min": 500, "debut_n_min": 100, "calibration_error_max": 0.05,
        "max_brier_delta_vs_market": 0.0, "max_log_loss_delta_vs_market": 0.0,
        "training_data_max_age_days": 45,
        "closing_market_provenance_required": True,
        "short_notice_slice_required": True,
    }


def _block(model_ll, model_brier, cal, mkt_ll, mkt_brier, elo_ll, n=1291):
    return {
        "n": n,
        "model": {"log_loss": model_ll, "brier": model_brier, "calibration_error": cal},
        "market_recorded_price_no_vig": {"log_loss": mkt_ll, "brier": mkt_brier},
        "elo_only": {"log_loss": elo_ll},
    }


def test_gates_pass_when_all_criteria_met():
    gates = screen.evaluate_gates(
        _contract(), _block(0.55, 0.19, 0.03, 0.58, 0.20, 0.65), 231, 15)
    assert gates["screen_verdict"] == "SCREEN_PASSED"
    assert all(c["pass"] for c in gates["criteria"].values())


def test_gates_fail_on_market_deltas():
    gates = screen.evaluate_gates(
        _contract(), _block(0.64, 0.226, 0.04, 0.589, 0.202, 0.68), 231, 15)
    assert gates["screen_verdict"] == "FAILED_SCREEN"
    assert not gates["criteria"]["brier_delta_vs_market_max"]["pass"]
    assert not gates["criteria"]["log_loss_delta_vs_market_max"]["pass"]
    assert gates["criteria"]["log_loss_strictly_better_than_elo_only"]["pass"]
    terms = gates["contract_terms_reported_not_gated_here"]
    assert terms["short_notice_slice_required"]["slice_status"] == \
        "NOT_IDENTIFIABLE_FROM_PINNED_SOURCES"


def test_gates_fail_on_small_n_and_calibration():
    gates = screen.evaluate_gates(
        _contract(), _block(0.55, 0.19, 0.09, 0.58, 0.20, 0.65, n=499), 99, 15)
    assert not gates["criteria"]["test_n_min"]["pass"]
    assert not gates["criteria"]["debut_slice_n_min"]["pass"]
    assert not gates["criteria"]["calibration_error_max"]["pass"]


# -------------------------------------------------------------------- pins ----

def test_load_pinned_files_verifies_hashes(tmp_path):
    payload = b"a,b\n1,2\n"
    import hashlib
    pins = {
        "market_source": {"files": [{
            "local_name": "m.csv", "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest()}]},
        "per_fight_source": {"files": []},
    }
    (tmp_path / "m.csv").write_bytes(payload)
    texts = screen.load_pinned_files(tmp_path, pins)
    assert texts["m.csv"] == "a,b\n1,2\n"
    (tmp_path / "m.csv").write_bytes(b"tampered")
    with pytest.raises(SystemExit):
        screen.load_pinned_files(tmp_path, pins)


# ------------------------------------------------------------------- audit ----

def test_audit_helpers_parse_greco_formats():
    assert screen._of("12 of 34") == (12, 34)
    assert screen._of("") == (0, 0)
    assert screen._elapsed_seconds(3, "2:30", "3 Rnd (5-5-5)") == 2 * 300 + 150
    assert screen._elapsed_seconds(1, "0:45", "3 Rnd (5-5-5)") == 45
    assert screen._elapsed_seconds("x", "0:45", "") is None


def test_entering_aggregates_are_strictly_prior():
    histories = {
        "alice a": [
            {"date": date(2020, 1, 1), "outcome": "W/L", "sig_l": 50, "sig_a": 100,
             "td_l": 2, "td_a": 4, "sub": 1, "seconds": 900},
            {"date": date(2021, 1, 1), "outcome": "L/W", "sig_l": 30, "sig_a": 60,
             "td_l": 1, "td_a": 2, "sub": 0, "seconds": 600},
        ]
    }
    entering = screen._entering(histories, "alice a", date(2021, 1, 1))
    # Only the 2020 bout is strictly prior to the 2021 bout.
    assert entering["wins"] == 1 and entering["losses"] == 0 and entering["n"] == 1
    assert entering["sig_per_fight"] == 50.0
    later = screen._entering(histories, "alice a", date(2022, 1, 1))
    assert later["wins"] == 1 and later["losses"] == 1 and later["n"] == 2


def test_results_json_shape(tmp_path):
    # The committed results file must carry the provenance label everywhere
    # the market appears as a baseline.
    results_path = _SCREEN_PATH.parent / "screen_results.json"
    if not results_path.exists():
        pytest.skip("screen_results.json not generated yet")
    result = json.loads(results_path.read_text(encoding="utf-8"))
    assert result["provenance_label"] == "RECORDED_PRICE_NOT_DK_CLOSE"
    assert result["gates"]["screen_verdict"] in ("SCREEN_PASSED", "FAILED_SCREEN")
