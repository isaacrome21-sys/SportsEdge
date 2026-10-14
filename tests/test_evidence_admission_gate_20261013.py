"""t127: shared anchored-admission gate, OFF (committed) and simulated ON states.

ON is simulated in-process with throwaway TEST CAs only; config flags stay false.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone

import pytest

from sportsedge import evidence_admission_gate as gate
from sportsedge import evidence_anchor as ea
from anchor_test_ca import TsaPairForTests, cutoff

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")

D = hashlib.sha256(b"t127-gate-bound-digest").hexdigest()
OTHER = hashlib.sha256(b"t127-gate-other").hexdigest()


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    return TsaPairForTests(tmp_path_factory.mktemp("t127gate"))


def test_off_refuses_even_a_valid_dual_tsa_bundle(pair):
    b = pair.bundle([D, OTHER])
    r = gate.anchored_admission(b, bound_sha256=D, event_cutoff=cutoff())
    assert not r.admitted and r.reason == "admission_not_activated"
    assert not ea.ADMISSION_ACTIVE and ea.load_config().admission_active is False


def test_off_refuses_garbage_without_parsing():
    assert gate.anchored_admission(None, bound_sha256="x", event_cutoff=None).reason == "admission_not_activated"


def test_on_admits_two_test_tsas(pair, monkeypatch):
    pair.activate(monkeypatch)
    r = gate.anchored_admission(pair.bundle([D, OTHER]), bound_sha256=D, event_cutoff=cutoff())
    assert r.admitted and r.reason == "admitted" and r.gen_time is not None


@pytest.mark.parametrize("case,reason", [
    ("uncovered", "anchor_does_not_cover_digest"),
    ("single", "tsa_quorum_not_met"),
    ("late", "gentime_after_cutoff_minus_margin"),
    ("naive", "cutoff_not_tz_aware"),
    ("baddigest", "bound_digest_invalid"),
    ("notmap", "malformed_bundle"),
])
def test_on_refusals(pair, monkeypatch, case, reason):
    pair.activate(monkeypatch)
    b = pair.bundle([D, OTHER], providers=("tsa_a",) if case == "single" else ("tsa_a", "tsa_b"))
    kw = {"bound_sha256": D, "event_cutoff": cutoff()}
    if case == "uncovered":
        b = pair.bundle([OTHER])
    elif case == "late":
        kw["event_cutoff"] = cutoff(-1)
    elif case == "naive":
        kw["event_cutoff"] = datetime.now()
    elif case == "baddigest":
        kw["bound_sha256"] = "ABC"
    elif case == "notmap":
        b = [b]
    r = gate.anchored_admission(b, **kw)
    assert not r.admitted and r.reason == reason


def test_production_seam_uses_configured_trust_and_refuses(pair, monkeypatch):
    # Runtime flag flipped but config still off/unpinned: configured path refuses.
    monkeypatch.setattr(ea, "ADMISSION_ACTIVE", True)
    r = gate.anchored_admission(pair.bundle([D]), bound_sha256=D, event_cutoff=cutoff())
    assert not r.admitted and r.reason == "admission_not_activated"
