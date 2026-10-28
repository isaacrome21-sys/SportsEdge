"""NBA props V2 evaluator type-hardening regressions (Oct 28, 2026).

Run: python3 -m pytest tests/test_nba_props_v2_evaluator_type_hardening_20261028.py

Defect record (adversarial pass, Oct 27–28, 2026; report-only until
this change): the evaluator's input boundary in
``sportsedge/forward_validation/nba_props.py`` had two residual type
escapes —

1. ``partition_nba_rows`` (and ``screen_nba_rows`` on the V1 path)
   read rows with ``.get`` unconditionally: a non-dict row (string,
   None, number, list) crashed with a raw ``AttributeError`` instead
   of a named fail-closed refusal.
2. The §5/§7.4 engine-stamp screen coerced ``n_prior`` through
   ``float()``, so the string ``"12"``, the string ``"1e2"``, the
   float ``12.0`` and ``inf`` all satisfied the ``>= 10`` prior-games
   comparison. A coerced stamp is not the count the engine declared.

Pin discipline: the family's byte pins cover the preregistration
documents (``PREREG_SHA256`` / ``PREREG_SHA256_V2``, recorded in
``research/nba_props_forward_20261020/SPEC_HASHES.txt`` and the
family configs) — NOT this module's bytes, whose sha256 appears in
no pin record. This change touches only the evaluator module's
input-boundary code and adds this test file; every pinned artifact
is byte-unchanged (proven below and by the existing suite's pin
tests), no threshold moves (``MIN_PRIOR_GAMES`` stays 10), and the
V2 quarantine is untouched: every prospective V2 COUNTED evaluation
still refuses ``V2_FREEZE_NOT_AUTHORIZED`` before any scoring.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sportsedge.forward_validation import (  # noqa: E402
    ForwardValidationRefusal,
    evaluate_nba_props_v2,
    load_nba_config,
    verify_prereg_document,
)
from sportsedge.forward_validation.nba_props import (  # noqa: E402
    PREREG_ID_V2,
    PREREG_SHA256_V2,
    partition_nba_rows,
    screen_nba_rows,
)

NON_MAPPINGS = ["a-string-row", None, 42, 4.5, ["prereg_id"], ("x",), True]


def stamp(**over):
    s = {"engine_id": "NBA_PROP_EMPIRICAL_V1", "sufficiency_met": True,
         "n_prior": 24, "pool_source": "POSITION_GROUP_EXPANDING_PIT",
         "store_provenance": "HOOPR_ESPN_PLAYER_BOX_V2_STORE",
         "limitation": "No participation/minutes/availability feed."}
    s.update(over)
    return s


def row(row_id="r1", **over):
    r = {"row_id": row_id, "sport": "NBA", "market": "player_points",
         "label": "PROSPECTIVE", "engine_stamp": stamp()}
    r.update(over)
    return r


def v1_cfg():
    return load_nba_config("player_points")


def v2_cfg():
    return load_nba_config("player_points", version="V2")


# --- escape 1: non-mapping rows refuse by name, never AttributeError ---

@pytest.mark.parametrize("bad", NON_MAPPINGS)
def test_partition_refuses_non_mapping_row_by_name(bad):
    with pytest.raises(ForwardValidationRefusal) as ei:
        partition_nba_rows([bad])
    assert ei.value.reason == "ROW_NOT_A_MAPPING"
    assert ei.value.detail["index"] == 0
    assert ei.value.detail["found_type"] == type(bad).__name__


def test_partition_refuses_non_mapping_after_valid_row():
    good = {"prereg_id": PREREG_ID_V2, "counting_class": "COUNTED",
            "row_id": "ok"}
    with pytest.raises(ForwardValidationRefusal) as ei:
        partition_nba_rows([good, None])
    assert ei.value.reason == "ROW_NOT_A_MAPPING"
    assert ei.value.detail["index"] == 1


@pytest.mark.parametrize("bad", NON_MAPPINGS)
def test_screen_refuses_non_mapping_row_by_name(bad):
    for cfg in (v1_cfg(), v2_cfg()):
        with pytest.raises(ForwardValidationRefusal) as ei:
            screen_nba_rows(cfg, [bad])
        assert ei.value.reason == "ROW_NOT_A_MAPPING"


def test_public_v2_entry_refuses_non_mapping_row_by_name():
    counted = row("c1", prereg_id=PREREG_ID_V2, counting_class="COUNTED")
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props_v2(v2_cfg(), [counted, "not-a-row"], [], [])
    assert ei.value.reason == "ROW_NOT_A_MAPPING"


def test_partition_of_dict_rows_unchanged():
    rows = [{"prereg_id": PREREG_ID_V2, "counting_class": "COUNTED",
             "row_id": "a"},
            {"prereg_id": PREREG_ID_V2, "row_id": "b"},
            {"row_id": "c"}]
    parts = partition_nba_rows(rows)
    assert [r["row_id"] for r in parts["v2_counted_rows"]] == ["a"]
    assert [r["row_id"] for r in parts["v2_research_rows"]] == ["b"]
    assert [r["row_id"] for r in parts["undeclared_rows"]] == ["c"]


# --- escape 2: n_prior must be a real int (bool excluded) ---

BAD_N_PRIOR = ["12", "1e2", " 12 ", "10", 12.0, 10.0, math.inf,
               -math.inf, math.nan, "nan", "inf", True, False, None,
               [12], {"n": 12}]


@pytest.mark.parametrize("bad", BAD_N_PRIOR)
def test_coerced_n_prior_is_refused(bad):
    kept, excl = screen_nba_rows(v1_cfg(), [row(engine_stamp=stamp(n_prior=bad))])
    assert kept == []
    reported = excl["no_engine_provenance_rows"]
    assert len(reported) == 1
    assert "N_PRIOR_MISSING_OR_BELOW_10" in reported[0]["problems"]


@pytest.mark.parametrize("good", [10, 11, 24, 100])
def test_real_int_n_prior_at_or_above_gate_admitted(good):
    kept, excl = screen_nba_rows(
        v1_cfg(), [row(engine_stamp=stamp(n_prior=good))])
    assert len(kept) == 1
    assert excl["no_engine_provenance_rows"] == []


@pytest.mark.parametrize("low", [0, 9, -3])
def test_real_int_n_prior_below_gate_still_refused(low):
    kept, excl = screen_nba_rows(
        v1_cfg(), [row(engine_stamp=stamp(n_prior=low))])
    assert kept == []
    assert "N_PRIOR_MISSING_OR_BELOW_10" in \
        excl["no_engine_provenance_rows"][0]["problems"]


def test_coerced_n_prior_refused_in_alternate_stamp_shapes():
    # Top-level stamp fields (no engine_stamp mapping).
    top = row("t1")
    del top["engine_stamp"]
    top.update(stamp(n_prior="12"))
    kept, excl = screen_nba_rows(v1_cfg(), [top])
    assert kept == []
    assert "N_PRIOR_MISSING_OR_BELOW_10" in \
        excl["no_engine_provenance_rows"][0]["problems"]
    # The phone lane's nba_prop_engine mapping shape.
    lane = row("t2")
    lane["nba_prop_engine"] = stamp(n_prior=math.inf)
    del lane["engine_stamp"]
    kept, excl = screen_nba_rows(v1_cfg(), [lane])
    assert kept == []
    assert "N_PRIOR_MISSING_OR_BELOW_10" in \
        excl["no_engine_provenance_rows"][0]["problems"]


# --- the quarantine is unchanged and still precedes the screen ---

def test_quarantine_still_refuses_every_prospective_counted_row():
    counted = row("q1", prereg_id=PREREG_ID_V2, counting_class="COUNTED")
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props_v2(v2_cfg(), [counted], [], [])
    assert ei.value.reason == "V2_FREEZE_NOT_AUTHORIZED"
    assert ei.value.detail["attempted_counted_rows"] == 1


def test_quarantine_gate_fires_before_stamp_screen():
    # Even a counted row whose stamp would fail the hardened screen is
    # refused by the freeze gate first — the hardening does not move,
    # weaken, or reorder the quarantine.
    counted = row("q2", prereg_id=PREREG_ID_V2, counting_class="COUNTED",
                  engine_stamp=stamp(n_prior="12"))
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props_v2(v2_cfg(), [counted], [], [])
    assert ei.value.reason == "V2_FREEZE_NOT_AUTHORIZED"


# --- pinned artifacts are byte-unchanged by this change ---

def test_prereg_pins_still_verify():
    assert PREREG_SHA256_V2 == (
        "069cbf661e6ca733e9bda54ee3bc8a02163b20a5"
        "df7fcbbc89b10d9419a6aa02")
    assert verify_prereg_document("V1")["sha256"] == (
        "54363908b1e2332a57af9b9263ac2f398438c81b2d366"
        "442b80667086657bc79")
    assert verify_prereg_document("V2")["sha256"] == PREREG_SHA256_V2
