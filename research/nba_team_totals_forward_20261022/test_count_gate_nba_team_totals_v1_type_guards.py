"""Type-guard regression tests for the count-admission gate
(`count_gate_nba_team_totals_v1.py`, V1.2 correction).

The V1.1 gate compared and coerced caller input at its boundary: a
`slate_date` was stringified and compared lexicographically, caller
config values were checked by equality alone, and wrong-typed records
or receipts escaped as raw AttributeErrors. Each test below reproduces
one pre-fix defect shape and asserts the post-fix named refusal, with
the evaluator spied to prove scoring is never invoked and nothing
reaches the ledger. The production default is untouched throughout:
`RECEIPT_SHA256 is None`; a future reviewed pin is simulated only by
in-process module constants (monkeypatch), never via the public API.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import count_gate_nba_team_totals_v1 as gate  # noqa: E402
import eval_nba_team_totals_v1 as ev  # noqa: E402
import test_eval_nba_team_totals_v1 as t  # noqa: E402

FIXTURE_RECEIPT = {
    "receipt": "NBA_TT_PIN_PUSH_RECEIPT_V1",
    "evaluator_sha256": gate.PINNED_EVALUATOR_SHA256,
    "pin_commit": gate.PIN_COMMIT,
    "pin_push_time_utc": "2026-10-23T02:55:00+00:00",
    "first_counted_slate": "2026-11-01",
    "attested_by": "test fixture",
    "attestation_source": "test fixture — not a production attestation",
}

POST_PIN = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def _install_receipt(tmp_path, obj=FIXTURE_RECEIPT, name="PIN_PUSH_RECEIPT.json"):
    p = tmp_path / name
    p.write_bytes(json.dumps(obj, indent=1).encode())
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


def _simulate_reviewed_pin(monkeypatch, receipt_path, digest):
    """Synthetic reviewed pin FOR TESTS ONLY; production receipt is absent."""
    monkeypatch.setattr(gate, "RECEIPT_PATH", receipt_path)
    monkeypatch.setattr(gate, "RECEIPT_SHA256", digest)


def _forbid_scoring(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SCORING_PATH_REACHED")
    monkeypatch.setattr(ev, "evaluate", forbidden)


def _pinned(monkeypatch, tmp_path):
    rp, sha = _install_receipt(tmp_path)
    _simulate_reviewed_pin(monkeypatch, rp, sha)


def _post_pin_game():
    return t.one_game("g1", 115, 110.5, 112)  # slate 2026-11-01, post-pin


# D1: the reported worst defect. Every timestamp the gate checks is
# forged post-pin; only the slate identity is pre-pin, and only its int
# shape defeated the old str() lexicographic comparison — the gate
# published (ledger written) and the row was silently downgraded to a
# per-row evaluator refusal. Post-fix: GATE_TYPE_INVALID at the gate,
# evaluator never invoked, nothing written.
def test_count_gate_int_slate_date_refused_before_scoring(monkeypatch,
                                                          tmp_path):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    tip = datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc)
    row = t.priced("gpre", "Tgpre", 115, slate="2026-10-20", tip=tip,
                   entry_t=tip - timedelta(hours=5))
    row["priced_at"] = "2026-11-01T12:00:00+00:00"
    row["slate_date"] = 20261020
    ents = t.entry_quotes("gpre", "Tgpre", 110.5, t=POST_PIN)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted([row], ents, [], {}, {}, [],
                             ledger_path=ledger)
    assert ei.value.code == "GATE_TYPE_INVALID"
    assert not ledger.exists()


# D1 (shapes): any slate_date that is not a canonical ISO YYYY-MM-DD
# string refuses by the type code — including an int naming an
# ON/AFTER-pin slate, which the old comparison also waved through.
@pytest.mark.parametrize("bad_slate", [
    None, True, 20261101, 2026.1101, "20261101", "2026/11/01",
    "2026-1-5", "2026-11-01T00:00:00+00:00", ["2026-11-01"],
])
def test_count_gate_slate_date_wrong_shape_refused(monkeypatch, tmp_path,
                                                   bad_slate):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    rows, ents, cls, res = _post_pin_game()
    rows[0]["slate_date"] = bad_slate
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, cls, res,
                             t.full_slates(["2026-11-01"]), [],
                             ledger_path=ledger)
    assert ei.value.code == "GATE_TYPE_INVALID"
    assert not ledger.exists()


# The semantic pre-pin check still fires under its own code for a
# well-typed pre-pin slate string (not masked by the type guard).
def test_count_gate_pre_pin_slate_string_refused_as_pre_pin(monkeypatch,
                                                            tmp_path):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    tip = datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc)
    row = t.priced("gpre", "Tgpre", 115, slate="2026-10-20", tip=tip,
                   entry_t=tip - timedelta(hours=5))
    row["priced_at"] = "2026-11-01T12:00:00+00:00"
    ents = t.entry_quotes("gpre", "Tgpre", 110.5, t=POST_PIN)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted([row], ents, [], {}, {}, [],
                             ledger_path=ledger)
    assert ei.value.code == "COUNTED_ROW_PRE_PIN"
    assert not ledger.exists()


# D2: caller config checked by equality alone admitted float twins of
# the frozen ints (9.0 == 9), which the evaluator then int()-coerced.
# Post-fix the frozen record must be repeated in type as well as value.
@pytest.mark.parametrize("override", [
    {"k": 9.0}, {"seed": 20261022.0}, {"resamples": 10000.0},
    {"k": 9.0, "seed": 20261022.0, "resamples": 10000.0},
])
def test_count_gate_config_float_twins_refused(monkeypatch, tmp_path,
                                               override):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    rows, ents, cls, res = _post_pin_game()
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, cls, res,
                             t.full_slates(["2026-11-01"]), [],
                             caller_config=override, ledger_path=ledger)
    assert ei.value.code == "FROZEN_EVALUATION_CONFIG_UNAUTHORIZED"
    assert not ledger.exists()


# D2 (bool / string numerics): a bool is not an int and a numeric string
# is not a count — both are deviations from the frozen record by name.
@pytest.mark.parametrize("override", [
    {"k": True}, {"k": "9"}, {"seed": "20261022"}, {"resamples": True},
])
def test_count_gate_config_bool_and_string_counts_refused(monkeypatch,
                                                          tmp_path,
                                                          override):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    rows, ents, cls, res = _post_pin_game()
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, cls, res,
                             t.full_slates(["2026-11-01"]), [],
                             caller_config=override, ledger_path=ledger)
    assert ei.value.code == "FROZEN_EVALUATION_CONFIG_UNAUTHORIZED"
    assert not ledger.exists()


# Positive control: a caller config that repeats the canonical config
# exactly (real ints, the ISO slate string, the clock-id list) is still
# accepted — the type guard did not change behavior for valid inputs.
def test_count_gate_config_exact_canonical_still_accepted(monkeypatch,
                                                          tmp_path):
    _pinned(monkeypatch, tmp_path)
    rows, ents, cls, res = _post_pin_game()
    canonical = {"first_counted_slate": "2026-11-01", "k": ev.FROZEN_K,
                 "seed": ev.FROZEN_SEED, "resamples": ev.FROZEN_RESAMPLES,
                 "clock_ids": list(gate.CANONICAL_CLOCK_IDS)}
    ledger = tmp_path / "ledger.jsonl"
    pub = gate.publish_counted(rows, ents, cls, res,
                               t.full_slates(["2026-11-01"]), [],
                               caller_config=canonical,
                               ledger_path=ledger)
    assert pub["evaluation"]["binding"] is True
    assert len(ledger.read_text().strip().splitlines()) == 1


# D3: a non-mapping row or quote element (or a mapping in place of the
# sequence) crashed the old gate with a raw AttributeError. Post-fix:
# GATE_TYPE_INVALID before scoring.
@pytest.mark.parametrize("rows,ents", [
    ([["not", "a", "dict"]], []),
    ([], ["not-a-dict"]),
    ({"g1": {}}, []),
    ("g1", []),
])
def test_count_gate_non_mapping_records_refused(monkeypatch, tmp_path,
                                                rows, ents):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, [], {}, {}, [],
                             ledger_path=ledger)
    assert ei.value.code == "GATE_TYPE_INVALID"
    assert not ledger.exists()


# D4: collections the gate forwards to the pinned evaluator are
# type-checked at the boundary instead of crashing inside it.
@pytest.mark.parametrize("kwargs", [
    {"close_quotes": "not-a-sequence"},
    {"close_quotes": [["not-a-dict"]]},
    {"results": []},
    {"results": {"g1": "not-a-mapping"}},
    {"slates": []},
    {"slates": {"2026-11-01": True}},
    {"missing_offers": {}},
])
def test_count_gate_forwarded_collections_type_refused(monkeypatch,
                                                       tmp_path, kwargs):
    _forbid_scoring(monkeypatch)
    _pinned(monkeypatch, tmp_path)
    rows, ents, cls, res = _post_pin_game()
    call = {"close_quotes": cls, "results": res,
            "slates": t.full_slates(["2026-11-01"]), "missing_offers": []}
    call.update(kwargs)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, call["close_quotes"],
                             call["results"], call["slates"],
                             call["missing_offers"], ledger_path=ledger)
    assert ei.value.code == "GATE_TYPE_INVALID"
    assert not ledger.exists()


# D5: a receipt file holding valid JSON of the wrong type (a list) with
# a matching installed hash crashed the old loader with a raw
# AttributeError. Post-fix: PIN_PUSH_RECEIPT_MALFORMED by name.
def test_count_gate_receipt_non_object_refused_by_name(monkeypatch,
                                                       tmp_path):
    _forbid_scoring(monkeypatch)
    rp, sha = _install_receipt(tmp_path, obj=[1, 2, 3],
                               name="PIN_PUSH_RECEIPT.json")
    _simulate_reviewed_pin(monkeypatch, rp, sha)
    rows, ents, cls, res = _post_pin_game()
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, cls, res,
                             t.full_slates(["2026-11-01"]), [],
                             ledger_path=ledger)
    assert ei.value.code == "PIN_PUSH_RECEIPT_MALFORMED"
    assert not ledger.exists()


# Refusal precedence is unchanged: with no pin installed (the
# production default), even wrong-typed input meets the receipt refusal
# first — the type guards sit behind the trust boundary, and the gate
# still fails closed exactly as before.
def test_count_gate_production_default_refusal_precedes_type_guards(
        monkeypatch, tmp_path):
    _forbid_scoring(monkeypatch)
    assert gate.RECEIPT_SHA256 is None
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted([["not", "a", "dict"]], [], [], {}, {}, [],
                             ledger_path=ledger)
    assert ei.value.code == "TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE"
    assert not ledger.exists()
