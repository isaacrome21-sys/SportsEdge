"""NBA props V2 evaluator integration tests (Oct 26, 2026).

Run: python3 -m pytest tests/test_nba_props_v2_evaluator_20261026.py

The V2 preregistration (PREREG_NBA_PROPS_FORWARD_V2, source
amendment) is a FINAL-CANDIDATE — NOT FROZEN: the owner approved the
source amendment for preparation and HELD the freeze until his four
§12 conditions verify. These tests prove the evaluator integration
the amendment requires, against the acceptance criteria of record:

1. CONTAMINATION: a mixed V1 / V2-research / undeclared / V2-counted
   row set yields a V2 verdict computed ONLY from V2 counted rows,
   with the verdict's row provenance explicit on the record; and a
   tampered V2 document fails its hash pin closed. The toxic load is
   exactly 130 fully-scorable rows: 60 V1 + 60 V2-research + 10
   undeclared. Since the Oct 26 freeze-gate repair (item 4), this
   test exercises the verdict math through the evaluator's internal
   scoring implementation (``_score_nba_props_v2``) as a research
   diagnostic — the public entry now refuses the counted attempt
   outright, which is item 4's regression; every assertion about
   the verdict math and the separation is unchanged in meaning, and
   no authorized counted verdict is produced here.
2. SEPARATION DEFAULTS: a V2 row without an explicit COUNTED class
   is research, never counted; a HISTORICAL V2 row is excluded from
   verdict math (no auto-activation of historical rows).
3. V1 UNCHANGED: the V1 pin verifies against the untouched V1
   document, V1 configs keep their frozen terms, and V2 configs
   differ from V1 only in the pin/status/boundary fields — every
   gate and threshold identical (the amendment changes the admitted
   store source, nothing else).
4. FREEZE GATE (owner ruling, Oct 26, 2026 — the independent
   review's Concern 1, a blocking acceptance finding): invoking the
   public evaluator directly with 100 synthetic V2 COUNTED,
   PROSPECTIVE, fully stamped rows while V2 is NOT FROZEN raises
   the named refusal V2_FREEZE_NOT_AUTHORIZED before any scoring —
   zero rows scored, no counted-row ids or verdict emitted, and the
   framework scoring function provably never invoked.
"""
from __future__ import annotations

import hashlib
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
from sportsedge.forward_validation import core as fw_core  # noqa: E402
from sportsedge.forward_validation.nba_props import (  # noqa: E402
    PREREG_ID_V1,
    PREREG_ID_V2,
    PREREG_SHA256,
    PREREG_SHA256_V2,
    _score_nba_props_v2,
    partition_nba_rows,
)

START = "2026-11-18T19:30:00-06:00"  # a post-freeze-style slate date
FAMILIES = ("player_points", "player_rebounds", "player_assists",
            "player_pra")
V1_DOC = ROOT / "research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md"
V2_DOC = ROOT / "research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V2.md"


def stamp(**over):
    s = {"engine_id": "NBA_PROP_EMPIRICAL_V1", "sufficiency_met": True,
         "n_prior": 24, "pool_source": "POSITION_GROUP_EXPANDING_PIT",
         "store_provenance": "HOOPR_ESPN_PLAYER_BOX_V2_STORE",
         "limitation": ("No participation/minutes/availability feed is "
                        "wired: probabilities are over realized outcomes.")}
    s.update(over)
    return s


def row(row_id, event, subject, *, disposition="PICKED",
        prereg_id=PREREG_ID_V2, counting_class="COUNTED", **over):
    r = {"row_id": row_id, "sport": "NBA", "family": "player_points",
         "market": "player_points", "event_id": event,
         "event_start": START, "subject_id": subject, "line": 24.5,
         "model_version": "NBA_PROP_EMPIRICAL_V1",
         "model_p": {"OVER": 0.62, "UNDER": 0.38},
         "entry_prices": {"OVER": -110, "UNDER": -110},
         "entry_captured_at": "2026-11-18T12:00:00-06:00",
         "recorded_at": "2026-11-18T12:00:30-06:00",
         "label": "PROSPECTIVE", "engine_stamp": stamp()}
    if disposition is not None:
        r["disposition"] = disposition
    if prereg_id is not None:
        r["prereg_id"] = prereg_id
    if counting_class is not None:
        r["counting_class"] = counting_class
    r.update(over)
    return r


def close(event, subject, *, over=-130, under=110):
    return {"event_id": event, "subject_id": subject,
            "market": "player_points", "line": 24.5,
            "prices": {"OVER": over, "UNDER": under},
            "captured_at": "2026-11-18T19:00:00-06:00"}


def outcome(event, subject, *, value=30.0):
    return {"event_id": event, "subject_id": subject,
            "market": "player_points", "value": value}


def v2_cfg():
    return load_nba_config("player_points", version="V2")


def beats_family(prefix, n_picked=50, n_passed=50, n_events=40):
    """§4-scale V2 counted family: picked CLV +0.0427, passed CLV 0."""
    rows, closes, outcomes = [], [], []
    for i in range(n_picked + n_passed):
        disp = "PICKED" if i < n_picked else "PASSED"
        ev, sub = f"{prefix}G{i % n_events}", f"{prefix} Player {i}"
        rows.append(row(f"{prefix}-{i}", ev, sub, disposition=disp))
        oc, uc = (-130, 110) if disp == "PICKED" else (-110, -110)
        closes.append(close(ev, sub, over=oc, under=uc))
        outcomes.append(outcome(ev, sub, value=30.0 if i % 2 else 18.0))
    return rows, closes, outcomes


def toxic_rows(prefix, n, **kw):
    """Strongly negative-CLV rows (-0.0798 each): if any of these
    entered the V2 sample, the picked-CLV leg and the verdict would
    visibly move. Closes/outcomes are supplied so the rows are fully
    scorable — only their identity/class may keep them out."""
    rows, closes, outcomes = [], [], []
    for i in range(n):
        ev, sub = f"{prefix}G{i}", f"{prefix} Player {i}"
        rows.append(row(f"{prefix}-{i}", ev, sub, disposition="PICKED",
                        **kw))
        closes.append(close(ev, sub, over=130, under=-150))
        outcomes.append(outcome(ev, sub, value=30.0))
    return rows, closes, outcomes


# ---------- pins: both documents verify; V1 untouched ----------

def test_both_prereg_documents_verify_against_their_pins():
    v1 = verify_prereg_document("V1")
    assert v1["sha256"] == PREREG_SHA256 == (
        "54363908b1e2332a57af9b9263ac2f398438c81b2d366"
        "442b80667086657bc79")
    # the V1 document on disk still hashes to the frozen value —
    # the original freeze is byte-unchanged on this branch
    assert hashlib.sha256(V1_DOC.read_bytes()).hexdigest() == v1["sha256"]
    v2 = verify_prereg_document("V2")
    assert v2["sha256"] == PREREG_SHA256_V2
    assert hashlib.sha256(V2_DOC.read_bytes()).hexdigest() == v2["sha256"]
    registry = (ROOT / "research/nba_props_forward_20261020"
                / "SPEC_HASHES.txt").read_text(encoding="utf-8")
    assert f"{PREREG_SHA256}  PREREG_NBA_PROPS_FORWARD_V1.md" in registry
    assert f"{PREREG_SHA256_V2}  PREREG_NBA_PROPS_FORWARD_V2.md" in registry


def test_tampered_v2_document_fails_pin_closed(tmp_path):
    tampered = tmp_path / "PREREG_NBA_PROPS_FORWARD_V2.md"
    tampered.write_bytes(V2_DOC.read_bytes() + b"\n<!-- drift -->\n")
    with pytest.raises(ForwardValidationRefusal) as ei:
        verify_prereg_document("V2", document_path=tampered)
    assert ei.value.reason == "PREREG_PIN_MISMATCH"
    assert ei.value.detail["expected"] == PREREG_SHA256_V2
    # and the honest document still verifies (the gate is the pin,
    # not a blanket refusal)
    assert verify_prereg_document("V2")["sha256"] == PREREG_SHA256_V2


def test_tampered_v1_document_fails_pin_closed(tmp_path):
    tampered = tmp_path / "PREREG_NBA_PROPS_FORWARD_V1.md"
    tampered.write_bytes(V1_DOC.read_bytes().replace(b"V1", b"V9", 1))
    with pytest.raises(ForwardValidationRefusal) as ei:
        verify_prereg_document("V1", document_path=tampered)
    assert ei.value.reason == "PREREG_PIN_MISMATCH"


# ---------- configs: V2 mirrors V1 except the amendment fields ----------

def test_v2_configs_mirror_v1_gates_and_carry_the_v2_pin():
    for family in FAMILIES:
        v1 = load_nba_config(family)
        v2 = load_nba_config(family, version="V2")
        for field in ("sport", "family", "markets", "engine_id",
                      "model_version", "market_form", "sides",
                      "over_side", "min_rows", "min_events",
                      "min_slates", "max_clv_missing_share",
                      "clv_beats_threshold", "close_max_age_minutes",
                      "picked_beats_passed_required"):
            assert getattr(v2, field) == getattr(v1, field), (family, field)
        assert v1.prereg_sha256 == PREREG_SHA256
        assert v1.status.startswith("FROZEN")
        assert v2.prereg.endswith("PREREG_NBA_PROPS_FORWARD_V2.md")
        assert v2.prereg_sha256 == PREREG_SHA256_V2
        assert "NOT FROZEN" in v2.status  # the freeze is HELD


def test_unknown_version_refused():
    with pytest.raises(ForwardValidationRefusal) as ei:
        load_nba_config("player_points", version="V3")
    assert ei.value.reason == "CONFIG_INVALID"


def test_v2_evaluation_rejects_a_v1_config():
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props_v2(load_nba_config("player_points"), [], [], [])
    assert ei.value.reason == "CONFIG_INVALID"


# ---------- separation: partition defaults fail closed ----------

def test_partition_defaults_fail_closed():
    parts = partition_nba_rows([
        row("a", "G1", "P A"),                                        # V2 counted
        row("b", "G2", "P B", counting_class="RESEARCH"),             # V2 research
        row("c", "G3", "P C", counting_class=None),                   # V2, no class -> research
        row("d", "G4", "P D", prereg_id=PREREG_ID_V1,
            counting_class=None),                                     # V1
        row("e", "G5", "P E", prereg_id=None, counting_class=None),   # undeclared
        row("f", "G6", "P F", prereg_id="SOMETHING_ELSE",
            counting_class="COUNTED"),                               # unknown test -> undeclared
    ])
    assert [r["row_id"] for r in parts["v2_counted_rows"]] == ["a"]
    assert [r["row_id"] for r in parts["v2_research_rows"]] == ["b", "c"]
    assert [r["row_id"] for r in parts["v1_rows"]] == ["d"]
    assert [r["row_id"] for r in parts["undeclared_rows"]] == ["e", "f"]


# ---------- contamination: the mixed-set verdict ----------

def test_mixed_row_set_verdict_counts_only_v2_counted_rows():
    counted, closes, outcomes = beats_family("v2c")
    v1_rows, v1_closes, v1_outs = toxic_rows(
        "v1x", 60, prereg_id=PREREG_ID_V1, counting_class=None)
    res_rows, res_closes, res_outs = toxic_rows(
        "v2r", 60, counting_class="RESEARCH")
    und_rows, und_closes, und_outs = toxic_rows(
        "und", 10, prereg_id=None, counting_class=None)
    mixed = counted + v1_rows + res_rows + und_rows
    # DIAGNOSTIC PATH (Oct 26 freeze-gate repair): the verdict math
    # and separation are proven against the evaluator's internal
    # scoring implementation. The public entry refuses this same
    # input with V2_FREEZE_NOT_AUTHORIZED while V2 is NOT FROZEN —
    # that refusal is the freeze-gate regression below — so routing
    # this proof through the public entry is no longer possible
    # without producing (or attempting) an authorized counted
    # verdict, which is exactly what must not happen pre-freeze.
    rec = _score_nba_props_v2(
        v2_cfg(), mixed, closes + v1_closes + res_closes + und_closes,
        outcomes + v1_outs + res_outs + und_outs, slates_completed=4)
    m = rec["markets"]["player_points"]
    # the verdict is the clean counted family's verdict, unmoved by
    # 130 fully-scorable toxic rows riding along in the input
    assert m["verdict"] == "BEATS_MARKET"
    assert m["verdict_sample_rows"] == 100
    assert m["picked_rows"] == 50 and m["passed_rows"] == 50
    assert m["clv"]["mean"] == pytest.approx(0.04274353876739567,
                                             abs=1e-12)
    # provenance is explicit: every scored row is a declared counted
    # row, and the counted list is exactly the scored set
    scored_ids = {r["row_id"] for r in m["rows"]}
    counted_ids = {r["row_id"] for r in counted}
    assert scored_ids == counted_ids
    assert set(rec["counted_row_ids"]) == counted_ids
    assert rec["prereg_id"] == PREREG_ID_V2
    assert rec["prereg_sha256"] == PREREG_SHA256_V2
    # every other bucket is reported, by id, and enters nothing
    sep = rec["separation"]
    assert sep["v2_counted_rows"]["count"] == 100
    assert sep["v1_rows"]["count"] == 60
    assert sep["v2_research_rows"]["count"] == 60
    assert sep["undeclared_rows"]["count"] == 10
    assert set(sep["v1_rows"]["row_ids"]) == {
        r["row_id"] for r in v1_rows}
    assert set(sep["v2_research_rows"]["row_ids"]) == {
        r["row_id"] for r in res_rows}
    assert set(sep["undeclared_rows"]["row_ids"]) == {
        r["row_id"] for r in und_rows}


def test_v2_row_without_counted_class_never_counts():
    # fully scorable on its face; only its missing class keeps it out
    r = row("noclass", "G1", "Player One", counting_class=None)
    rec = evaluate_nba_props_v2(v2_cfg(), [r], [close("G1", "Player One")],
                                [outcome("G1", "Player One")],
                                slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["graded_rows"] == 0 and m["rows"] == []
    assert m["verdict"] == "INSUFFICIENT_SAMPLE"
    assert rec["counted_row_ids"] == []
    assert rec["separation"]["v2_research_rows"]["row_ids"] == ["noclass"]


def test_historical_v2_row_is_never_auto_counted():
    hist = row("hist", "G1", "Player One",
               recorded_at="2026-11-18T21:05:00-06:00",
               label="HISTORICAL")
    rec = evaluate_nba_props_v2(
        v2_cfg(), [hist], [close("G1", "Player One")],
        [outcome("G1", "Player One")], slates_completed=4)
    m = rec["markets"]["player_points"]
    assert m["graded_rows"] == 0
    assert rec["excluded"]["historical_rows"] == ["hist"]
    assert rec["counted_row_ids"] == []


# ---------- freeze gate: the evaluator refuses unauthorized counting
# (owner ruling, Oct 26, 2026 — independent review Concern 1) ----------

def test_counted_evaluation_refused_while_v2_not_frozen(monkeypatch):
    # The exact probe the independent review exposed: 100 synthetic
    # V2 COUNTED, PROSPECTIVE, fully stamped rows — otherwise
    # eligible on their face (this same family scores BEATS_MARKET
    # through the diagnostic path in the contamination test above).
    rows, closes, outcomes = beats_family("fz")
    assert len(rows) == 100
    # Spy on the framework scoring entry the evaluator calls: if the
    # gate ever lets a counted attempt through to scoring, the spy
    # both records it and raises, so the test cannot pass silently.
    scoring_calls = []

    def scoring_spy(*args, **kwargs):
        scoring_calls.append((args, kwargs))
        raise AssertionError(
            "core.evaluate_family invoked behind the freeze gate")

    monkeypatch.setattr(fw_core, "evaluate_family", scoring_spy)
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props_v2(v2_cfg(), rows, closes, outcomes,
                              slates_completed=4)
    # (a) the named refusal, naming every attempted counted row
    assert ei.value.reason == "V2_FREEZE_NOT_AUTHORIZED"
    assert ei.value.detail["attempted_counted_rows"] == 100
    assert set(ei.value.detail["attempted_counted_row_ids"]) == {
        r["row_id"] for r in rows}
    # (b)+(c) the raise IS the record: no verdict record, no counted
    # row ids, and no verdict were emitted — the call returned
    # nothing at all.
    # (d) the underlying scoring function was never invoked, so zero
    # rows were scored.
    assert scoring_calls == []

def test_mutating_loaded_config_status_cannot_unlock_counting(monkeypatch):
    """The freeze signal is authenticated from disk, never from cfg.status.

    FamilyConfig is mutable. This is a direct adversarial call to the
    public evaluator, retaining the authentic V2 prereg path and SHA.
    It must refuse the same otherwise-eligible 100-row attempt.
    """
    cfg = v2_cfg()
    assert "NOT FROZEN" in cfg.status
    cfg.status = "FROZEN — caller-forged status"
    rows, closes, outcomes = beats_family("spoof")
    assert len(rows) == 100

    calls = []

    def scoring_spy(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("forged freeze state reached scoring")

    monkeypatch.setattr(fw_core, "evaluate_family", scoring_spy)
    with pytest.raises(ForwardValidationRefusal) as ei:
        evaluate_nba_props_v2(cfg, rows, closes, outcomes,
                              slates_completed=4)
    assert ei.value.reason == "V2_FREEZE_NOT_AUTHORIZED"
    assert ei.value.detail["attempted_counted_rows"] == 100
    assert set(ei.value.detail["attempted_counted_row_ids"]) == {
        r["row_id"] for r in rows}
    assert calls == []

