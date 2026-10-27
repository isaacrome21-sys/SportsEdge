"""Adversarial tests for the count-admission gate
(`count_gate_nba_team_totals_v1.py`) — the mandatory forward-ledger
write boundary for NBA Team Totals Forward Test V1.

The pinned evaluator is a pure scoring function of caller-supplied
records/config; counted publication must instead be bound to a trusted
immutable pin-push receipt, the frozen config recorded in
FREEZE_RECORD.md, and per-row post-pin provenance. Each refusal test
spies on the evaluator to prove the scoring path is never invoked and
that zero counted rows/metrics reach the ledger.
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

# Fixture receipt: synthetic governance fixture for tests only. It is
# written to a tmp path and pinned by hash through the gate's explicit
# receipt arguments; it is NOT an installed production receipt.
FIXTURE_RECEIPT = {
    "receipt": "NBA_TT_PIN_PUSH_RECEIPT_V1",
    "evaluator_sha256": gate.PINNED_EVALUATOR_SHA256,
    "pin_commit": gate.PIN_COMMIT,
    "pin_push_time_utc": "2026-10-23T02:55:00+00:00",
    "first_counted_slate": "2026-11-01",
    "attested_by": "test fixture",
    "attestation_source": "test fixture — not a production attestation",
}


def _install_receipt(tmp_path):
    p = tmp_path / "PIN_PUSH_RECEIPT.json"
    p.write_bytes(json.dumps(FIXTURE_RECEIPT, indent=1).encode())
    return p, hashlib.sha256(p.read_bytes()).hexdigest()


def _forbid_scoring(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("SCORING_PATH_REACHED")
    monkeypatch.setattr(ev, "evaluate", forbidden)


def _one_post_pin_game():
    return t.one_game("g1", 115, 110.5, 112)  # slate 2026-11-01, post-pin


# No trusted receipt installed (the production default) -> refuse by
# name before scoring; zero counted rows/metrics are emitted.
def test_count_gate_no_receipt_refuses_before_scoring(monkeypatch,
                                                      tmp_path):
    _forbid_scoring(monkeypatch)
    rows, ents, cls, res = _one_post_pin_game()
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, cls, res,
                             t.full_slates(["2026-11-01"]), [],
                             ledger_path=ledger)
    assert ei.value.code == "TRUSTED_PIN_PUSH_RECEIPT_UNAVAILABLE"
    assert not ledger.exists()


# A caller-written receipt (here claiming an early September pin time)
# whose bytes do not match the pinned receipt hash -> refused.
def test_count_gate_forged_receipt_refused(monkeypatch, tmp_path):
    _forbid_scoring(monkeypatch)
    _, genuine_sha = _install_receipt(tmp_path)
    forged = dict(FIXTURE_RECEIPT,
                  pin_push_time_utc="2026-09-01T00:00:00+00:00",
                  first_counted_slate="2026-09-01")
    p = tmp_path / "forged_receipt.json"
    p.write_bytes(json.dumps(forged, indent=1).encode())
    rows, ents, cls, res = _one_post_pin_game()
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, cls, res,
                             t.full_slates(["2026-11-01"]), [],
                             ledger_path=ledger, receipt_path=p,
                             receipt_sha256=genuine_sha)
    assert ei.value.code == "PIN_PUSH_RECEIPT_HASH_MISMATCH"
    assert not ledger.exists()


# Genuine receipt, but fully stamped rows priced BEFORE the pin-push
# time (the pre-pin backfill shape) -> the whole publication refuses.
def test_count_gate_pre_pin_rows_refused(monkeypatch, tmp_path):
    _forbid_scoring(monkeypatch)
    rp, sha = _install_receipt(tmp_path)
    tip = datetime(2026, 10, 2, 0, 0, tzinfo=timezone.utc)
    et = datetime(2026, 10, 1, 19, 0, tzinfo=timezone.utc)
    rows = [t.priced("gpre", "Tgpre", 115, slate="2026-10-01", tip=tip,
                     entry_t=et)]
    ents = t.entry_quotes("gpre", "Tgpre", 110.5, t=et)
    ledger = tmp_path / "ledger.jsonl"
    with pytest.raises(gate.CountAdmissionRefused) as ei:
        gate.publish_counted(rows, ents, [], {}, {}, [],
                             ledger_path=ledger, receipt_path=rp,
                             receipt_sha256=sha)
    assert ei.value.code == "COUNTED_ROW_PRE_PIN"
    assert not ledger.exists()


# Genuine receipt and post-pin rows, but any caller config deviation —
# weakened k/seed/resamples, substituted clock identities, a backdated
# first counted slate, or a smuggled caller pin time — refuses.
def test_count_gate_forged_config_refused(monkeypatch, tmp_path):
    _forbid_scoring(monkeypatch)
    rp, sha = _install_receipt(tmp_path)
    rows, ents, cls, res = _one_post_pin_game()
    ledger = tmp_path / "ledger.jsonl"
    overrides = [
        {"k": 8},
        {"seed": 7},
        {"resamples": 400},
        {"clock_ids": ["CLOCK_0"]},
        {"first_counted_slate": "2026-10-01"},
        {"pin_push_time_utc": "2026-09-01T00:00:00+00:00"},
    ]
    for override in overrides:
        with pytest.raises(gate.CountAdmissionRefused) as ei:
            gate.publish_counted(rows, ents, cls, res,
                                 t.full_slates(["2026-11-01"]), [],
                                 caller_config=override,
                                 ledger_path=ledger, receipt_path=rp,
                                 receipt_sha256=sha)
        assert ei.value.code == "FROZEN_EVALUATION_CONFIG_UNAUTHORIZED"
    assert not ledger.exists()


# Genuine receipt + canonical gate-derived config + fully stamped
# post-pin rows: the counted path runs the pinned evaluator and the
# forward ledger gains exactly one publication record with metrics.
def test_count_gate_genuine_post_pin_publishes(tmp_path):
    rp, sha = _install_receipt(tmp_path)
    rows, ents, cls, res, dates = t._big(
        8, 12, mean_fn=lambda i: 113.0 if i % 2 else 108.0,
        final_fn=lambda i: 113.0 if i % 2 else 108.0)
    ledger = tmp_path / "ledger.jsonl"
    pub = gate.publish_counted(rows, ents, cls, res,
                               t.full_slates(dates), [],
                               ledger_path=ledger, receipt_path=rp,
                               receipt_sha256=sha)
    out = pub["evaluation"]
    assert out["binding"] is True
    assert out["review_slate"] == dates[6]
    assert "metrics" in out
    lines = ledger.read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["gate"] == gate.GATE_VERSION
    assert rec["gate_evaluator_sha256"] == gate.PINNED_EVALUATOR_SHA256
    assert rec["pin_push_receipt_sha256"] == sha
    assert rec["counts"]["sample_rows"] == 7 * 24
    assert rec["verdict"] == out["verdict"]
    assert rec["play_authority"] is False
    # The gate's own pin document attests this module's exact bytes.
    pin_doc = (HERE / "COUNT_GATE_PIN.md").read_text()
    module_sha = hashlib.sha256(
        Path(gate.__file__).read_bytes()).hexdigest()
    assert module_sha in pin_doc and gate.GATE_VERSION in pin_doc
