"""t127: dual-TSA anchor wired into the MLB receipt journal via the shared gate.

OFF (committed config): refused with admission_not_activated, journal untouched.
ON is simulated in-process with throwaway TEST CAs only.
"""
import hashlib
import shutil
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import evidence_anchor as ea
from sportsedge import mlb_source as ms
from tests.anchor_test_ca import TsaPairForTests, cutoff
from tests.test_mlb_receipt_journal_replay_20261013 import T0, _capture_one

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")
NOW = lambda: datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    return TsaPairForTests(tmp_path_factory.mktemp("t127rc"))


def _rec(tmp_path):
    _, r = _capture_one(tmp_path)
    return r.record_sha256


def test_off_refused_and_journal_unchanged(tmp_path, pair):
    assert ea.load_config().admission_active is False and not ea.ADMISSION_ACTIVE
    sha = _rec(tmp_path)
    before = (tmp_path / ms.RECEIPT_JOURNAL_NAME).read_bytes()
    r = ms.admit_anchored_receipt(tmp_path, sha, tsa_bundle=pair.bundle([sha]), event_cutoff=cutoff())
    assert r == {"admitted": False, "external_time_anchor": False, "research_only": True,
                 "reason": "RECEIPT_ANCHOR_REFUSED:admission_not_activated"}
    assert (tmp_path / ms.RECEIPT_JOURNAL_NAME).read_bytes() == before
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(days=1))) == 1


def test_off_refuses_before_reading_missing_journal(tmp_path):
    r = ms.admit_anchored_receipt(tmp_path / "nope", "a" * 64, tsa_bundle=None, event_cutoff=None)
    assert r["reason"] == "RECEIPT_ANCHOR_REFUSED:admission_not_activated"


def test_on_admits_anchored_receipt(tmp_path, pair, monkeypatch):
    pair.activate(monkeypatch)
    sha = _rec(tmp_path)
    r = ms.admit_anchored_receipt(tmp_path, sha, tsa_bundle=pair.bundle([sha]),
                                  event_cutoff=cutoff(), verifier_now=NOW())
    assert r["admitted"] and r["external_time_anchor"] and r["research_only"] and r["sequence"] == 1


@pytest.mark.parametrize("case,reason", [
    ("uncovered", "anchor_does_not_cover_digest"),
    ("single", "tsa_quorum_not_met"),
    ("not_in_journal", "record_not_in_journal"),
    ("tampered", "RECEIPT_RECORD_TAMPERED"),
    ("receipt_after_cutoff", "receipt_after_cutoff"),
])
def test_on_refusals(tmp_path, pair, monkeypatch, case, reason):
    pair.activate(monkeypatch)
    sha = _rec(tmp_path)
    kw = {"event_cutoff": cutoff(), "verifier_now": NOW()}
    if case == "uncovered":
        b = pair.bundle([hashlib.sha256(b"x").hexdigest()])
    elif case == "single":
        b = pair.bundle([sha], providers=("tsa_b",))
    elif case == "not_in_journal":
        sha = hashlib.sha256(b"unknown").hexdigest()
        b = pair.bundle([sha])
    elif case == "tampered":
        j = tmp_path / ms.RECEIPT_JOURNAL_NAME
        j.write_bytes(j.read_bytes().replace(b'"byte_length":2', b'"byte_length":3')
                      .replace(b'"byte_length": 2', b'"byte_length": 3'))
        b = pair.bundle([sha])
    else:
        # anchor genTime pregame for a later event, but receipt after a cutoff
        # that is still after the quorum genTime is impossible here; use a
        # cutoff before the receipt and a margin-satisfying quorum via patch.
        monkeypatch.setattr(ms, "receipt_supports_as_of", lambda e, a: False)
        b = pair.bundle([sha])
    r = ms.admit_anchored_receipt(tmp_path, sha, tsa_bundle=b, **kw)
    assert not r["admitted"] and r["reason"].startswith("RECEIPT_ANCHOR_REFUSED:")
    assert reason in r["reason"]
