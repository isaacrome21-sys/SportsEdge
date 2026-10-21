"""Universal forward-validation framework tests (Oct 20, 2026).

Run: python3 -m pytest tests/test_forward_validation_20261020.py

Coverage: verbatim-mechanics parity against the FROZEN Part 2 package
(boot / de-vig — the pinned evaluator file is hash-checked, never
modified); the fail-closed refusals (version mismatch, post-start
records, missing timestamps, duplicates, invalid probabilities); the
frozen §4.5 close-rule dispositions (all five CLV_MISSING reasons plus
the exactly-60-minutes boundary); insufficiency (INSUFFICIENT_SAMPLE /
INSUFFICIENT_CLOSE_DATA, never a verdict); a hand-checked CLV example;
a synthetic end-to-end family reaching BEATS_MARKET; and the YES_ONLY
(anytime-TD form) selection + CLV path.
"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge.forward_validation import (  # noqa: E402
    ForwardValidationRefusal,
    config_from_dict,
    evaluate_family,
    load_config,
)
from sportsedge.forward_validation import stats as fw_stats  # noqa: E402

PART2 = ROOT / "research" / "nfl_props_part2_20261018"
START = "2026-11-01T18:00:00-05:00"


def _load_part2_module(filename: str):
    spec = importlib.util.spec_from_file_location(f"part2_{filename}", PART2 / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def base_cfg(**over):
    doc = {"sport": "TEST", "family": "SYNTH", "markets": ["SYNTH"],
           "engine_id": "SYNTH_ENGINE", "model_version": "synth_v1",
           "sides": ["OVER", "UNDER"], "over_side": "OVER",
           "min_rows": 4, "min_events": 2, "status": "DRAFT — NOT FROZEN"}
    doc.update(over)
    return config_from_dict(doc)


def row(row_id="r1", event="E1", subject="P1", *, line=10.5, p_over=0.62,
        over_price=-110, under_price=-110, version="synth_v1",
        entry_at="2026-11-01T12:00:00-05:00", recorded_at="2026-11-01T12:00:30-05:00",
        label="PROSPECTIVE", start=START):
    return {"row_id": row_id, "sport": "TEST", "family": "SYNTH",
            "market": "SYNTH", "event_id": event, "event_start": start,
            "subject_id": subject, "line": line, "model_version": version,
            "model_p": {"OVER": p_over, "UNDER": 1.0 - p_over},
            "entry_prices": {"OVER": over_price, "UNDER": under_price},
            "entry_captured_at": entry_at, "recorded_at": recorded_at,
            "label": label}


def close(event="E1", subject="P1", *, line=10.5, over=-130, under=110,
          at="2026-11-01T17:30:00-05:00"):
    prices = {"OVER": over, "UNDER": under}
    return {"event_id": event, "subject_id": subject, "market": "SYNTH",
            "line": line, "prices": prices, "captured_at": at}


def outcome(event="E1", subject="P1", value=14.0):
    return {"event_id": event, "subject_id": subject, "market": "SYNTH",
            "value": value}


def synth_family(n_rows=12, per_event=3, close_over=-130, close_under=110):
    rows, closes, outcomes = [], [], []
    for i in range(n_rows):
        ev = f"E{i // per_event}"
        rows.append(row(row_id=f"r{i}", event=ev, subject=f"P{i}"))
        closes.append(close(event=ev, subject=f"P{i}",
                            over=close_over, under=close_under))
        outcomes.append(outcome(event=ev, subject=f"P{i}",
                                value=14.0 if i % 3 else 8.0))
    return rows, closes, outcomes


# ---------- parity with the frozen Part 2 mechanics ----------

def test_pinned_evaluator_hash_unchanged():
    digest = hashlib.sha256(
        (PART2 / "eval_nfl_props_calibration_v1.py").read_bytes()).hexdigest()
    assert digest == "66de56155e3c36f90c1f39c648b24e724328ec86056dee0e9adbed57281bc25b"


def test_boot_parity_with_pinned_evaluator():
    ev = _load_part2_module("eval_nfl_props_calibration_v1.py")
    vals = [0.03, -0.01, 0.05, 0.02, 0.04, -0.02, 0.01, 0.06]
    blocks = ["g1", "g1", "g2", "g2", "g3", "g3", "g4", "g4"]
    assert fw_stats.boot(vals, blocks) == ev.boot(vals, blocks)


def test_devig_parity_with_part2_pricer():
    pricer = _load_part2_module("price_nfl_props_part2.py")
    for pair in [(-110, -110), (-130, 110), (150, -170), (-105, -115)]:
        assert fw_stats.devig_pair(*pair) == pricer.devig_pair(*pair)
        assert fw_stats.american_to_decimal(pair[0]) == pricer.american_to_decimal(pair[0])


# ---------- hand-checked CLV ----------

def test_handchecked_clv():
    # Entry -110/-110 -> no-vig 0.5000. Model p_over 0.62 -> EV(over) =
    # 0.62 * (1 + 100/110) - 1 = +0.14545 > EV(under): selected OVER.
    # Close -130/+110 -> raw 0.565217 / 0.476190, sum 1.041407,
    # no-vig over = 0.542744. CLV = 0.542744 - 0.500000 = +0.042744.
    rec = evaluate_family(base_cfg(), [row()], [close()], [outcome()])
    m = rec["markets"]["SYNTH"]
    scored = m["rows"][0]
    assert scored["selected_side"] == "OVER"
    assert scored["selected_result"] == "WIN"
    assert scored["clv"] == pytest.approx(0.04274353876739567, abs=1e-12)
    assert m["clv"]["mean"] == pytest.approx(0.04274353876739567, abs=1e-12)
    assert m["graded_rows"] == 1
    # log loss: model -ln(0.62); market -ln(0.5)
    assert m["logloss_model"] == pytest.approx(0.47803580094299973, abs=1e-9)
    assert m["logloss_market_entry"] == pytest.approx(0.6931471805599453, abs=1e-9)


def test_exact_ev_tie_is_tie_and_excluded():
    # p 0.50/0.50 at -110/-110 -> equal EVs -> TIE: no W/L, no CLV.
    rec = evaluate_family(base_cfg(), [row(p_over=0.5)], [close()], [outcome()])
    m = rec["markets"]["SYNTH"]
    assert m["rows"][0]["selected_side"] == "TIE"
    assert m["rows"][0]["clv"] is None
    assert m["win_loss"] == {"wins": 0, "losses": 0, "pushes": 0,
                             "win_rate_ex_pushes": None}


def test_push_is_graded_but_out_of_win_loss():
    rec = evaluate_family(base_cfg(),
                          [row(line=14.0)], [close(line=14.0)],
                          [outcome(value=14.0)])
    m = rec["markets"]["SYNTH"]
    assert m["rows"][0]["outcome_side"] == "PUSH"
    assert m["win_loss"]["pushes"] == 1
    assert m["win_loss"]["win_rate_ex_pushes"] is None
    assert m["logloss_model"] is None


# ---------- refusals ----------

def test_version_mismatch_refused():
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [row(version="synth_v2")], [], [])
    assert ei.value.reason == "MODEL_VERSION_MISMATCH"
    assert ei.value.detail["found"] == "synth_v2"


def test_post_start_prospective_record_refused():
    bad = row(recorded_at="2026-11-01T18:00:01-05:00")
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [bad], [], [])
    assert ei.value.reason == "POST_START_RECORD"


def test_historical_post_start_record_excluded_not_scored():
    hist = row(row_id="hist1", subject="P9",
               recorded_at="2026-11-01T19:45:00-05:00", label="HISTORICAL")
    rows, closes, outcomes = synth_family()
    rows.append(hist)
    rec = evaluate_family(base_cfg(min_rows=10, min_events=4),
                          rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert rec["excluded"]["historical_rows"] == ["hist1"]
    assert all(r["row_id"] != "hist1" for r in m["rows"])
    assert m["graded_rows"] == 12


def test_missing_entry_timestamp_refused():
    bad = row()
    del bad["entry_captured_at"]
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [bad], [], [])
    assert ei.value.reason == "RECORD_MISSING_TIMESTAMP"


def test_missing_close_timestamp_refused():
    bad_close = close()
    del bad_close["captured_at"]
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [row()], [bad_close], [outcome()])
    assert ei.value.reason == "CLOSE_RECORD_MISSING_TIMESTAMP"


def test_duplicate_prospective_row_refused():
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [row(), row(row_id="r2")], [], [])
    assert ei.value.reason == "DUPLICATE_PROSPECTIVE_ROW"


def test_probabilities_not_summing_to_one_refused():
    bad = row()
    bad["model_p"] = {"OVER": 0.62, "UNDER": 0.30}
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [bad], [], [])
    assert ei.value.reason == "MODEL_PROBABILITY_INVALID"


def test_missing_entry_price_refused():
    bad = row()
    bad["entry_prices"] = {"OVER": -110}
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(base_cfg(), [bad], [], [])
    assert ei.value.reason == "PRICE_INVALID"


def test_late_entry_excluded_per_row():
    late = row(entry_at="2026-11-01T18:00:00-05:00")  # at start: not pre-event
    rec = evaluate_family(base_cfg(), [late], [close()], [outcome()])
    m = rec["markets"]["SYNTH"]
    assert rec["excluded"]["late_entry_rows"] == ["r1"]
    assert m["graded_rows"] == 0


# ---------- the five CLV_MISSING reasons ----------

def _one_row_market(**kwargs):
    rec = evaluate_family(base_cfg(), [row()], kwargs.get("closes", []),
                          [outcome()])
    return rec["markets"]["SYNTH"]


def test_no_close_row_reason():
    m = _one_row_market(closes=[])
    assert m["rows"][0]["clv_missing_reason"] == "NO_CLOSE_ROW"
    assert m["rows"][0]["selected_result"] == "WIN"  # stays in win/loss
    assert m["rows"][0]["clv"] is None


def test_line_moved_reason():
    m = _one_row_market(closes=[close(line=11.5)])
    assert m["rows"][0]["clv_missing_reason"] == "LINE_MOVED"


def test_close_single_sided_reason():
    c = close()
    c["prices"] = {"OVER": -130}
    m = _one_row_market(closes=[c])
    assert m["rows"][0]["clv_missing_reason"] == "CLOSE_SINGLE_SIDED"


def test_close_not_prekickoff_reason():
    m = _one_row_market(closes=[close(at="2026-11-01T18:00:00-05:00")])
    assert m["rows"][0]["clv_missing_reason"] == "CLOSE_NOT_PREKICKOFF"


def test_close_stale_reason_and_exactly_60_minutes_readable():
    stale = _one_row_market(closes=[close(at="2026-11-01T16:59:59-05:00")])
    assert stale["rows"][0]["clv_missing_reason"] == "CLOSE_STALE"
    edge = _one_row_market(closes=[close(at="2026-11-01T17:00:00-05:00")])
    assert edge["rows"][0]["close_status"] == "READABLE"  # exactly 60:00
    assert edge["rows"][0]["clv"] is not None


# ---------- insufficiency and verdicts ----------

def test_insufficient_sample_never_a_verdict():
    rows, closes, outcomes = synth_family(n_rows=6)
    rec = evaluate_family(base_cfg(min_rows=100, min_events=40),
                          rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert m["verdict"] == "INSUFFICIENT_SAMPLE"
    assert m["gates"]["min_rows"] == {"required": 100, "actual": 6, "pass": False}
    assert m["clv"]["mean"] > 0  # a positive CLV cannot rescue the sample


def test_insufficient_events_gate():
    # 12 rows but all in ONE event: the events gate binds independently.
    rows, closes, outcomes = synth_family(n_rows=12, per_event=12)
    rec = evaluate_family(base_cfg(min_rows=10, min_events=40),
                          rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert m["verdict"] == "INSUFFICIENT_SAMPLE"
    assert m["gates"]["min_events"]["pass"] is False


def test_insufficient_close_data():
    # Gates met, but 3 of 12 rows (25%) have no close -> INSUFFICIENT_CLOSE_DATA.
    rows, closes, outcomes = synth_family()
    closes = closes[:9]
    rec = evaluate_family(base_cfg(min_rows=10, min_events=4),
                          rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert m["verdict"] == "INSUFFICIENT_CLOSE_DATA"
    assert m["clv_missing_share"] == pytest.approx(0.25)
    assert m["clv_missing_by_reason"] == {"NO_CLOSE_ROW": 3}


def test_synthetic_end_to_end_beats_market():
    rows, closes, outcomes = synth_family()
    rec = evaluate_family(base_cfg(min_rows=10, min_events=4),
                          rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert m["verdict"] == "BEATS_MARKET"
    assert m["clv"]["ci95_lo"] > 0
    assert m["clv"]["n_events_clustered"] == 4
    assert m["win_loss"]["wins"] == 8 and m["win_loss"]["losses"] == 4
    assert rec["config_status"] == "DRAFT — NOT FROZEN"
    assert len(rec["config_sha256"]) == 64


def test_does_not_beat_market_when_clv_negative():
    rows, closes, outcomes = synth_family(close_over=110, close_under=-130)
    rec = evaluate_family(base_cfg(min_rows=10, min_events=4),
                          rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert m["verdict"] == "DOES_NOT_BEAT_MARKET"
    assert m["clv"]["mean"] < 0


def test_unscored_row_reported_not_invented():
    rows, closes, outcomes = synth_family(n_rows=3)
    outcomes = outcomes[:2]  # third row has no realized outcome
    rec = evaluate_family(base_cfg(), rows, closes, outcomes)
    m = rec["markets"]["SYNTH"]
    assert m["graded_rows"] == 2
    assert rec["excluded"]["unscored_rows"] == ["r2"]


# ---------- YES_ONLY (anytime-TD form) ----------

def yes_cfg(**over):
    doc = {"sport": "NFL", "family": "TWO_PLUS_TD", "markets": ["TWO_PLUS_TD"],
           "engine_id": "NFL_PROP_ENGINES_V1", "model_version": "nfl_prop_engines_v1@test",
           "market_form": "YES_ONLY", "sides": ["YES"], "over_side": "YES",
           "min_rows": 3, "min_events": 2, "status": "DRAFT — NOT FROZEN"}
    doc.update(over)
    return config_from_dict(doc)


def yes_row(row_id, event, subject, *, p_yes, yes_price, line=1.5):
    return {"row_id": row_id, "sport": "NFL", "family": "TWO_PLUS_TD",
            "market": "TWO_PLUS_TD", "event_id": event, "event_start": START,
            "subject_id": subject, "line": line,
            "model_version": "nfl_prop_engines_v1@test",
            "model_p": {"YES": p_yes}, "entry_prices": {"YES": yes_price},
            "entry_captured_at": "2026-11-01T12:00:00-05:00",
            "recorded_at": "2026-11-01T12:00:30-05:00", "label": "PROSPECTIVE"}


def test_yes_only_picked_rule_and_raw_clv():
    # Entry Yes +200 -> raw implied 1/3 = 0.3333. Model 0.40 > 0.3333: PICKED.
    # Close Yes +150 -> raw implied 0.40. CLV = 0.40 - 0.3333 = +0.0667.
    rows = [yes_row("y1", "E1", "P1", p_yes=0.40, yes_price=200),
            yes_row("y2", "E1", "P2", p_yes=0.40, yes_price=200),
            yes_row("y3", "E2", "P3", p_yes=0.40, yes_price=200),
            yes_row("y4", "E2", "P4", p_yes=0.20, yes_price=200)]  # PASS row
    closes = [{"event_id": r["event_id"], "subject_id": r["subject_id"],
               "market": "TWO_PLUS_TD", "line": 1.5,
               "prices": {"YES": 150}, "captured_at": "2026-11-01T17:30:00-05:00"}
              for r in rows]
    outcomes = [{"event_id": r["event_id"], "subject_id": r["subject_id"],
                 "market": "TWO_PLUS_TD", "value": v}
                for r, v in zip(rows, [2.0, 1.0, 3.0, 2.0])]
    rec = evaluate_family(yes_cfg(), rows, closes, outcomes)
    m = rec["markets"]["TWO_PLUS_TD"]
    by_id = {r["row_id"]: r for r in m["rows"]}
    assert by_id["y1"]["selected_side"] == "YES"
    assert by_id["y1"]["clv"] == pytest.approx(0.4 - 1 / 3, abs=1e-9)
    assert by_id["y1"]["selected_result"] == "WIN"
    assert by_id["y2"]["selected_result"] == "LOSS"
    assert by_id["y4"]["selected_side"] == "PASS"
    assert by_id["y4"]["clv"] is None  # passed rows carry no verdict CLV
    assert m["verdict_sample_rows"] == 3  # min_rows binds picked rows
    assert m["verdict"] == "BEATS_MARKET"


# ---------- config loading ----------

def test_load_real_config_and_invalid_config(tmp_path):
    cfg = load_config(ROOT / "sportsedge" / "forward_validation"
                      / "configs" / "nfl_targets.json")
    assert cfg.sport == "NFL" and cfg.family == "TARGETS"
    assert cfg.status.startswith("DRAFT")
    bad = tmp_path / "bad.json"
    bad.write_text('{"sport": "X", "family": "Y", "markets": ["Y"],'
                   ' "engine_id": "E", "model_version": "v",'
                   ' "market_form": "THREE_SIDED"}')
    with pytest.raises(ForwardValidationRefusal) as ei:
        load_config(bad)
    assert ei.value.reason == "CONFIG_INVALID"
