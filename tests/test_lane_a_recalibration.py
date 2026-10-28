"""Lane A vNext probability-recalibration layer (UNVALIDATED, ADOPTED).

The layer implements the one adjustment supported by the 2026-10-28
EV-band calibration diagnostic: p_used = implied + k*(model_p - implied)
with k re-estimated from the trailing graded record and floored at 0.
On the diagnostic's pooled record (183 decided legs with a printed
model p) the fit is k = -0.461, i.e. floored to 0 today.

These tests pin the safety properties, not a validation:

- the config flag defaults to TRUE since the owner-delegated adoption
  of Oct 28, 2026 (it defaulted to FALSE before the adoption);
- with the flag off, Lane A pricing output is BYTE-IDENTICAL to the
  pre-layer engine (golden sha256 over a fixed offline fixture, plus
  object-identity at the apply seam);
- k estimation is honest about sample size (below 180 decided legs
  with a printed model p: INSUFFICIENT_SAMPLE, no point estimate);
- a negative fit floors to k = 0, so p_used collapses to the market
  break-even and the derived EV is exactly zero;
- when applied, both the raw model_p and p_used are exposed on the row
  and logged, and the raw engine values are never mutated or hidden.

All fixtures are offline; no network, no betting authority. The layer
was adopted on Oct 28, 2026 by owner-delegated decision (see
research/lane_a_recalibration_20261028/ADOPTION_RECORD.md) and is
wired into card production via sportsedge.lane_a_card_gates; it
remains UNVALIDATED.
"""
import copy
import hashlib
import importlib.util
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "free_models_recalibration_test", ROOT / "artifacts" / "free_models.py")
engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(engine)

from sportsedge import lane_a_recalibration as rc

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
KICKOFF = "2026-10-21T00:05:00Z"
FRESH_QUOTE = "2026-10-20T11:59:00Z"  # 60s before NOW

# Golden Lane A pricing output for the fixture below, generated from
# the engine on main BEFORE this layer existed (2026-10-28, two
# separate processes, identical result). The layer adds no code to the
# engine, so this hash must survive the layer's presence untouched.
GOLDEN_CARD_SHA256 = (
    "644d078d2c9c759782765cb64c595c763b79ec9959621a7cea53b584e2804535"
)

# The diagnostic's published pooled fit (calibration block of its
# summary.json): 183 decided legs with a printed model p, k = -0.461.
DIAGNOSTIC_SUMMARY = {
    "calibration": {
        "brier_n_legs": 183,
        "brier_model_p": 0.2740,
        "brier_market_implied": 0.2404,
        "shrink_fit_k_pooled": -0.461,
    }
}


def _fixture_rows():
    rows = []
    base = {"sport": "MLB", "away": "Los Angeles Dodgers",
            "home": "Milwaukee Brewers", "market": "TOTAL", "line": 14.5,
            "kickoff": KICKOFF, "quote_captured_at": FRESH_QUOTE}
    rows.append(dict(base, side="UNDER", odds=150))
    rows.append(dict(base, side="OVER", odds=-170))
    nba = {"sport": "NBA", "away": "Boston Celtics",
           "home": "New York Knicks", "kickoff": KICKOFF,
           "quote_captured_at": FRESH_QUOTE}
    rows.append(dict(nba, market="ML", side="AWAY", odds=120))
    rows.append(dict(nba, market="ML", side="HOME", odds=-140))
    rows.append(dict(nba, market="SPREAD", line=-4.5, side="HOME", odds=-110))
    rows.append(dict(nba, market="SPREAD", line=4.5, side="AWAY", odds=-110))
    return rows


def _fixture_card():
    return engine.run({"lines": _fixture_rows()}, now=NOW, auto_context=False)


def _canonical_bytes(obj) -> bytes:
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()


def _graded_legs(n_wins: int, n_legs: int, model_p=0.62, implied_p=0.52):
    """Deterministic graded record: first n_wins legs won, rest lost."""
    rows = []
    for i in range(n_legs):
        rows.append({
            "model_p": model_p,
            "implied_p": implied_p,
            "outcome": "WIN" if i < n_wins else "LOSS",
        })
    return rows


def _lane_a_result(model_p=0.62, implied_p=0.52, push_p=0.0, odds=-110):
    """A synthetic priced-result dict in the engine's result shape."""
    dec = 1.0 + 100.0 / 110.0
    raw_ev = model_p * (dec - 1.0) - (1.0 - model_p - push_p)
    view = {
        "lane": "LANE_A_INDEPENDENT",
        "estimate_p": model_p,
        "push_p": push_p,
        "loss_p": 1.0 - model_p - push_p,
        "ev_per_dollar": round(raw_ev, 6),
        "book_break_even_p": implied_p,
    }
    return {
        "schema": "SPORTSEDGE_FREE_RESEARCH_V1",
        "status": "RESEARCH_POSITIVE_EV_UNVALIDATED",
        "game": "Alpha @ Beta",
        "selection": "Beta ML",
        "market": "ML",
        "odds_american": odds,
        "estimate_p": model_p,
        "push_p": push_p,
        "ev_per_dollar": view["ev_per_dollar"],
        "pricing_lanes": {"lane_a_independent": view,
                          "lane_b_anchored": {"lane": "LANE_B"}},
        "independent_projection": view,
        "validated_profitability": False,
        "research_only": True,
    }


# ------------------------------------------------------------ flag default

def test_flag_defaults_to_true_since_adoption():
    # Owner-delegated adoption, Oct 28, 2026: the layer is the card
    # gates' probability basis, so the module default is now True.
    # Flag-off behavior remains available (and pinned below) through
    # explicit enabled=False calls.
    assert rc.RECALIBRATION_ENABLED is True


# ------------------------------------------------- flag-off byte identity

def test_flag_off_engine_output_byte_identical_to_golden():
    card = _fixture_card()
    blob = _canonical_bytes(card)
    assert hashlib.sha256(blob).hexdigest() == GOLDEN_CARD_SHA256
    assert b"recalibration" not in blob
    assert b"p_used" not in blob


def test_flag_off_apply_returns_the_same_object():
    result = _lane_a_result()
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    out = rc.apply_recalibration(result, estimate, enabled=False)
    assert out is result
    assert "recalibration" not in out
    rows = [result]
    out_rows = rc.apply_recalibration_to_rows(rows, estimate, enabled=False)
    assert out_rows is rows


def test_flag_off_serialization_unchanged_after_apply():
    result = _fixture_card()["evaluated_rows"][0]
    before = _canonical_bytes(result)
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    out = rc.apply_recalibration(result, estimate, enabled=False)
    assert _canonical_bytes(out) == before


# ------------------------------------------------------- k estimation

def test_diagnostic_summary_fit_reproduces_negative_k_floored():
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    assert estimate.n_decided_legs == 183
    assert estimate.k_raw == pytest.approx(-0.461)
    assert estimate.k_used == 0.0
    assert estimate.reason == rc.REASON_NEGATIVE_FIT_FLOORED_AT_ZERO
    assert estimate.source == rc.SOURCE_DIAGNOSTIC_SUMMARY_FIT


def test_rows_refit_negative_fit_floored():
    # implied 0.52, model 0.62, realized 90/200 = 0.45: the model's
    # deviations were anti-informative; analytic fit k = -0.70.
    estimate = rc.estimate_k(_graded_legs(90, 200))
    assert estimate.n_decided_legs == 200
    assert estimate.k_raw == pytest.approx(-0.70)
    assert estimate.k_used == 0.0
    assert estimate.reason == rc.REASON_NEGATIVE_FIT_FLOORED_AT_ZERO


def test_rows_refit_positive_fit_kept():
    # implied 0.52, model 0.62, realized 114/200 = 0.57: analytic
    # fit k = +0.50, kept unfloored above zero.
    estimate = rc.estimate_k(_graded_legs(114, 200))
    assert estimate.k_raw == pytest.approx(0.50)
    assert estimate.k_used == pytest.approx(0.50)
    assert estimate.reason == rc.REASON_ESTIMATED
    assert estimate.ci95_low is not None and estimate.ci95_high is not None
    assert estimate.ci95_low < estimate.k_raw < estimate.ci95_high


def test_insufficient_sample_reports_no_point_estimate():
    # A strong signal on 179 decided legs is still below the
    # diagnostic's sufficiency: k = 0, no point estimate surfaced.
    estimate = rc.estimate_k(_graded_legs(150, 179))
    assert estimate.n_decided_legs == 179
    assert estimate.k_raw is None
    assert estimate.k_used == 0.0
    assert estimate.reason == rc.REASON_INSUFFICIENT_SAMPLE


def test_pushes_and_unprinted_rows_do_not_count_toward_sample():
    rows = _graded_legs(120, 160)
    rows += [{"model_p": 0.62, "implied_p": 0.52, "outcome": "PUSH"}
             for _ in range(40)]
    rows += [{"implied_p": 0.52, "outcome": "WIN"} for _ in range(40)]
    estimate = rc.estimate_k(rows)
    assert estimate.n_decided_legs == 160
    assert estimate.reason == rc.REASON_INSUFFICIENT_SAMPLE


def test_degenerate_record_with_no_model_deviation():
    rows = [{"model_p": 0.52, "implied_p": 0.52,
             "outcome": "WIN" if i % 2 else "LOSS"} for i in range(200)]
    estimate = rc.estimate_k(rows)
    assert estimate.k_raw is None
    assert estimate.k_used == 0.0
    assert estimate.reason == rc.REASON_DEGENERATE_NO_MODEL_DEVIATION


def test_summary_missing_fit_is_a_named_refusal():
    with pytest.raises(ValueError, match="RECALIBRATION_SUMMARY_FIT_MISSING"):
        rc.estimate_k_from_summary({})
    with pytest.raises(ValueError, match="RECALIBRATION_SUMMARY_FIT_MISSING"):
        rc.estimate_k_from_summary({"calibration": {"brier_n_legs": 183}})


# ------------------------------------------------------------- the floor

def test_floor_k_zero_collapses_p_used_to_implied():
    assert rc.recalibrate_probability(0.871, 0.524, 0.0) == pytest.approx(0.524)
    assert rc.recalibrate_probability(0.30, 0.61, 0.0) == pytest.approx(0.61)


def test_negative_k_is_refused_not_applied():
    with pytest.raises(ValueError, match="RECALIBRATION_K_NEGATIVE"):
        rc.recalibrate_probability(0.62, 0.52, -0.46)


def test_positive_k_shrinks_toward_model_without_overshoot():
    p_used = rc.recalibrate_probability(0.62, 0.52, 0.5)
    assert p_used == pytest.approx(0.57)
    assert 0.52 < p_used < 0.62


# ------------------------------------------------------- applied rows

def test_applied_with_todays_k_zero_presents_zero_claimed_edge():
    # The diagnostic's consequence, on a real engine-priced row: with
    # k floored to 0, p_used is the break-even probability and the
    # recalibrated EV is exactly zero -- while the raw engine values
    # remain on the row, untouched and visible.
    card = _fixture_card()
    result = next(r for r in card["evaluated_rows"]
                  if r["selection"].startswith("UNDER"))
    assert result["ev_per_dollar"] > 0.30  # raw claimed edge, pre-layer
    before = copy.deepcopy(result)
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    out = rc.apply_recalibration(result, estimate, enabled=True)
    assert result == before  # caller's object never mutated
    block = out["recalibration"]
    assert block["status"] == "APPLIED"
    assert block["k"] == 0.0
    assert block["k_raw"] == pytest.approx(-0.461)
    assert block["model_p"] == before["pricing_lanes"]["lane_a_independent"]["estimate_p"]
    assert block["p_used"] == pytest.approx(block["implied_p"])
    assert block["ev_per_dollar"] == pytest.approx(0.0, abs=5e-6)
    assert block["ev_per_dollar_model_p"] == before["ev_per_dollar"]
    # Raw numbers stay exactly where the engine put them.
    assert out["estimate_p"] == before["estimate_p"]
    assert out["ev_per_dollar"] == before["ev_per_dollar"]
    assert (out["pricing_lanes"]["lane_a_independent"]
            == before["pricing_lanes"]["lane_a_independent"])
    # The gates' view, if adoption ever wires it: zero claimed edge.
    assert rc.effective_ev(out) == pytest.approx(0.0, abs=5e-6)
    assert rc.effective_probability(out) == pytest.approx(block["implied_p"])


def test_applied_positive_k_row_math_and_raw_preserved():
    result = _lane_a_result(model_p=0.62, implied_p=0.52, odds=-110)
    before = copy.deepcopy(result)
    estimate = rc.estimate_k(_graded_legs(114, 200))  # k = +0.50
    out = rc.apply_recalibration(result, estimate, enabled=True)
    block = out["recalibration"]
    assert block["p_used"] == pytest.approx(0.57)
    # ev = 0.57 * (100/110) - 0.43 = 0.088182 (push 0, odds -110)
    assert block["ev_per_dollar"] == pytest.approx(0.088182, abs=1e-6)
    assert block["ev_per_dollar_model_p"] == before["ev_per_dollar"]
    assert out["estimate_p"] == before["estimate_p"]
    assert result == before


def test_applied_missing_lane_a_view_is_visibly_not_applied():
    result = {"game": "Alpha @ Beta", "selection": "Beta ML",
              "odds_american": -110, "estimate_p": 0.62}
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    out = rc.apply_recalibration(result, estimate, enabled=True)
    assert out["recalibration"]["status"] == "NOT_APPLIED_INPUT_MISSING"
    assert "p_used" not in out["recalibration"]
    assert rc.effective_ev(out) is None  # no raw ev on this dict either


# ------------------------------------------------------------- logging

def test_log_line_records_both_raw_and_used_probabilities(caplog):
    result = _lane_a_result(model_p=0.62, implied_p=0.52, odds=-110)
    estimate = rc.estimate_k(_graded_legs(114, 200))
    with caplog.at_level(logging.INFO, logger="sportsedge.lane_a_recalibration"):
        rc.apply_recalibration(result, estimate, enabled=True)
    lines = [r.getMessage() for r in caplog.records
             if r.name == "sportsedge.lane_a_recalibration"]
    assert len(lines) == 1
    assert "model_p=0.620000" in lines[0]
    assert "p_used=0.570000" in lines[0]
    assert "k=0.500000" in lines[0]


def test_flag_off_emits_no_log_lines(caplog):
    result = _lane_a_result()
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    with caplog.at_level(logging.INFO, logger="sportsedge.lane_a_recalibration"):
        rc.apply_recalibration(result, estimate, enabled=False)
    assert [r for r in caplog.records
            if r.name == "sportsedge.lane_a_recalibration"] == []


def test_rows_apply_logs_one_line_per_priced_row(caplog):
    rows = _fixture_card()["evaluated_rows"]
    estimate = rc.estimate_k_from_summary(DIAGNOSTIC_SUMMARY)
    with caplog.at_level(logging.INFO, logger="sportsedge.lane_a_recalibration"):
        out = rc.apply_recalibration_to_rows(rows, estimate, enabled=True)
    assert len(out) == len(rows)
    assert all("recalibration" in r for r in out)
    lines = [r.getMessage() for r in caplog.records
             if r.name == "sportsedge.lane_a_recalibration"
             and "model_p=" in r.getMessage()]
    assert len(lines) == len(rows)
    assert all("model_p=" in line and "p_used=" in line for line in lines)
