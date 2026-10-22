"""Eval-infra repairs (Oct 22, 2026): the three defects reproduced against
forward_validation/core.py before this fix —

1. calibration_deciles rank-sliced tie blocks, making reported bucket
   errors an artifact of input order, and degenerated below n=10.
2. Outcome ingestion coerced values with bare float(): strings/bools
   scored silently, NaN silently scored as a PUSH, inf as a win, and
   malformed records crashed with raw KeyError/TypeError; duplicate
   outcome keys silently overwrote.
3. crps_candidate / crps_baseline means ran over independently filtered
   row sets (unmatched cohorts) with no counts and no paired delta.

These tests pin the repaired behavior. The frozen Part 2 / Part 2B
scorers carry their own copies and are NOT touched by this change.
"""
import pytest

from sportsedge.forward_validation import (
    ForwardValidationRefusal, config_from_dict, evaluate_family)
from sportsedge.forward_validation.core import calibration_deciles

START = "2026-11-01T18:00:00-05:00"


def _cfg(**over):
    doc = {"sport": "TEST", "family": "SYNTH", "markets": ["SYNTH"],
           "engine_id": "SYNTH_ENGINE", "model_version": "synth_v1",
           "sides": ["OVER", "UNDER"], "over_side": "OVER",
           "min_rows": 1, "min_events": 1, "status": "DRAFT"}
    doc.update(over)
    return config_from_dict(doc)


def _row(rid="r1", event="E1", subject="P1", line=24.5, p_over=0.62, **extra):
    r = {"row_id": rid, "sport": "TEST", "family": "SYNTH",
         "market": "SYNTH", "event_id": event, "event_start": START,
         "subject_id": subject, "line": line, "model_version": "synth_v1",
         "model_p": {"OVER": p_over, "UNDER": 1.0 - p_over},
         "entry_prices": {"OVER": -110, "UNDER": -110},
         "entry_captured_at": "2026-11-01T12:00:00-05:00",
         "recorded_at": "2026-11-01T12:00:30-05:00", "label": "PROSPECTIVE"}
    r.update(extra)
    return r


def _outcome(value, event="E1", subject="P1", market="SYNTH"):
    return {"event_id": event, "subject_id": subject, "market": market,
            "value": value}


# ---------------------------------------------------------------- defect 1

def _cal_rows(p, realized):
    return {"p_reference": p, "reference_realized": realized}


def test_calibration_ties_never_split_and_error_is_order_invariant():
    # Perfectly calibrated: 100 rows at p=0.5, exactly half realized.
    zeros_first = ([_cal_rows(0.5, 0.0)] * 50 + [_cal_rows(0.5, 1.0)] * 50)
    interleaved = [_cal_rows(0.5, float(i % 2)) for i in range(100)]
    for rows in (zeros_first, interleaved):
        dec = calibration_deciles(rows)
        assert len(dec) == 1  # one distinct p value -> one bucket
        assert dec[0]["mean_p"] == 0.5 and dec[0]["realized_rate"] == 0.5
        assert dec[0]["n"] == 100
        assert abs(dec[0]["mean_p"] - dec[0]["realized_rate"]) == 0.0


def test_calibration_below_floor_emits_nothing():
    assert calibration_deciles(
        [_cal_rows(0.3 + 0.05 * i, float(i % 2)) for i in range(9)]) == []
    assert calibration_deciles(
        [_cal_rows(0.5, 1.0)] * 5) == []
    assert calibration_deciles([]) == []


def test_calibration_distinct_values_keep_decile_shape_and_identity():
    rows = [_cal_rows(0.30 + 0.004 * i, float(i % 2)) for i in range(100)]
    dec = calibration_deciles(rows)
    assert len(dec) == 10
    assert [d["bucket"] for d in dec] == list(range(10))
    assert all(d["n"] == 10 for d in dec)
    assert all(dec[k]["p_max"] < dec[k + 1]["p_min"] for k in range(9))
    assert dec[-1]["p_max"] == max(r["p_reference"] for r in rows)


def test_calibration_straddling_tie_block_stays_whole():
    rows = ([_cal_rows(0.5, 1.0)] * 12
            + [_cal_rows(0.60 + 0.01 * i, float(i % 2)) for i in range(18)])
    dec = calibration_deciles(rows)
    tied = [d for d in dec if d["p_min"] == 0.5]
    assert len(tied) == 1 and tied[0]["n"] == 12
    assert tied[0]["realized_rate"] == 1.0
    assert all(dec[k]["p_max"] < dec[k + 1]["p_min"]
               for k in range(len(dec) - 1))


# ---------------------------------------------------------------- defect 2

def test_outcome_valid_value_still_scores():
    rec = evaluate_family(_cfg(), [_row()], [], [_outcome(27)])
    m = rec["markets"]["SYNTH"]
    assert m["win_loss"] == {"wins": 1, "losses": 0, "pushes": 0,
                             "win_rate_ex_pushes": 1.0}


@pytest.mark.parametrize("bad", ["27", "0.9", "abc", True, False, None,
                                 float("nan"), float("inf"), float("-inf")])
def test_outcome_non_numeric_or_nonfinite_value_refused(bad):
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(_cfg(), [_row()], [], [_outcome(bad)])
    assert ei.value.reason == "OUTCOME_VALUE_INVALID"


@pytest.mark.parametrize("bad_record", [
    {"subject_id": "P1", "market": "SYNTH", "value": 27},          # no event
    {"event_id": "E1", "subject_id": "P1", "value": 27},            # no market
    {"event_id": "E1", "subject_id": "P1", "market": "SYNTH"},      # no value
    "not-a-dict",
])
def test_outcome_malformed_record_refused_not_crash(bad_record):
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(_cfg(), [_row()], [], [bad_record])
    assert ei.value.reason == "OUTCOME_RECORD_INVALID"


def test_outcome_duplicate_key_refused_even_when_consistent():
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_family(_cfg(), [_row()], [],
                        [_outcome(27), _outcome(10)])
    assert ei.value.reason == "OUTCOME_DUPLICATE"
    with pytest.raises(ForwardValidationRefusal):
        evaluate_family(_cfg(), [_row()], [],
                        [_outcome(27), _outcome(27)])


def test_outcome_fractional_value_on_counting_scale_is_adapters_job():
    # The framework floor refuses non-numbers, not implausible numbers:
    # 0.9 on a 24.5 line scores (UNDER) exactly as before — scale rules
    # belong to adapters/configs, documented in _index_outcomes.
    rec = evaluate_family(_cfg(), [_row()], [], [_outcome(0.9)])
    assert rec["markets"]["SYNTH"]["win_loss"]["losses"] == 1


# ---------------------------------------------------------------- defect 3

def _crps_rows():
    rows, outcomes = [], []
    specs = [("A", 0.10, 0.30), ("B", 0.10, 0.30),
             ("C", 0.50, None), ("D", 0.50, None)]
    for i, (tag, cand, base) in enumerate(specs):
        extra = {"crps_candidate": cand}
        if base is not None:
            extra["crps_baseline"] = base
        rows.append(_row(rid=f"r{tag}", event=f"E{i}", subject=f"P{i}",
                         line=10.5, **extra))
        outcomes.append(_outcome(20, event=f"E{i}", subject=f"P{i}"))
    return rows, outcomes


def test_crps_summary_uses_matched_cohort_with_counts_and_delta():
    rows, outcomes = _crps_rows()
    m = evaluate_family(_cfg(), rows, [], outcomes)["markets"]["SYNTH"]
    # Matched rows are A,B only: candidate 0.10 vs baseline 0.30.
    # The unmatched C,D candidate values must not move either mean.
    assert m["crps_n_matched"] == 2
    assert m["crps_candidate"] == pytest.approx(0.10)
    assert m["crps_baseline"] == pytest.approx(0.30)
    assert m["crps_paired_delta"] == pytest.approx(-0.20)


def test_crps_summary_empty_when_no_matched_rows():
    rec = evaluate_family(_cfg(), [_row()], [], [_outcome(27)])
    m = rec["markets"]["SYNTH"]
    assert m["crps_candidate"] is None and m["crps_baseline"] is None
    assert m["crps_n_matched"] == 0 and m["crps_paired_delta"] is None
