"""t141: S3 object-version binding (owner ruling 2026-10-14). Mocked S3 only; no AWS."""
from __future__ import annotations

import hashlib
import io
import json
import os

import pytest

from sportsedge import anchor_payload_binding as apb
from sportsedge.anchor_payload_binding import (BindingError, S3BindingLedger, admit_s3_bound_payload,
                                               bind_s3_leaf, verify_s3_bound_leaf)

BODY = b"synthetic MLB_RECEIPT_JOURNAL_ANCHOR_V1 segment 0001\n"
SHA = hashlib.sha256(BODY).hexdigest()
MD5 = hashlib.md5(BODY).hexdigest()
V1 = "3HL4kqtJlcpXroDTDmJ.rmSpXd3dIbrHY"
V2 = "Q8n0xvT5tAj7.pk3E_2c9M1xYwX1Zt0a"
BASE = dict(schema="MLB_RECEIPT_JOURNAL_ANCHOR_V1", bucket="sportsedge-anchor-test",
            key="mlb/journal/2026-10-14/seg-0001.jsonl", version_id=V1, payload_sha256=SHA,
            receipt_id="rcpt:2026-10-14:000001", anchor_id="anc:mlb:0001")
EXP = dict(expected_payload_sha256=SHA, expected_receipt_id=BASE["receipt_id"],
           expected_anchor_id=BASE["anchor_id"])


class FakeS3:
    """boto3-shaped get_object over an in-memory versioned store."""

    def __init__(self, versions=None, *, respond_version=..., raise_exc=None, etag=None):
        self.versions = versions if versions is not None else {V1: BODY}
        self.respond_version = respond_version
        self.raise_exc = raise_exc
        self.etag = etag
        self.calls = []

    def get_object(self, *, Bucket, Key, VersionId):
        self.calls.append((Bucket, Key, VersionId))
        if self.raise_exc:
            raise self.raise_exc
        if VersionId not in self.versions:
            raise KeyError("NoSuchVersion")
        data = self.versions[VersionId]
        rv = VersionId if self.respond_version is ... else self.respond_version
        resp = {"Body": io.BytesIO(data), "ETag": f'"{self.etag or hashlib.md5(data).hexdigest()}"'}
        if rv is not None:
            resp["VersionId"] = rv
        return resp


def rec(**k):
    return bind_s3_leaf(**{**BASE, **k}).as_record()


def test_valid_binding_verifies_and_fetches_exact_version():
    s3 = FakeS3()
    assert verify_s3_bound_leaf(rec(), s3_client=s3, **EXP) == (True, "OK")
    assert s3.calls == [(BASE["bucket"], BASE["key"], V1)]


def test_leaf_commits_every_field():
    base = bind_s3_leaf(**BASE).leaf
    for k, v in [("bucket", "sportsedge-anchor-tes2"), ("key", BASE["key"] + "x"),
                 ("version_id", V2), ("payload_sha256", "0" * 64),
                 ("receipt_id", "rcpt:other"), ("anchor_id", "anc:other")]:
        assert bind_s3_leaf(**{**BASE, k: v}).leaf != base, k


@pytest.mark.parametrize("vid,reason", [(None, "S3_VERSION_ID_MISSING"), ("", "S3_VERSION_ID_MISSING"),
                                        ("null", "S3_VERSION_ID_NULL"), ("a b", "S3_VERSION_ID_INVALID"),
                                        (123, "S3_VERSION_ID_MISSING")])
def test_missing_or_null_version_refused_at_bind(vid, reason):
    with pytest.raises(BindingError, match=reason):
        bind_s3_leaf(**{**BASE, "version_id": vid})


@pytest.mark.parametrize("vid", [None, "", "null"])
def test_missing_version_in_record_refused_at_verify(vid):
    r = rec()
    r["version_id"] = vid
    ok, why = verify_s3_bound_leaf(r, s3_client=FakeS3(), **EXP)
    assert not ok and why.startswith("S3_VERSION_ID")


@pytest.mark.parametrize("etag", [MD5, f'"{MD5}"', MD5.upper(), MD5 + "-3", f'"{MD5}-12"'])
def test_etag_in_place_of_digest_refused(etag):
    with pytest.raises(BindingError, match="ETAG_NOT_ACCEPTED_AS_DIGEST"):
        bind_s3_leaf(**{**BASE, "payload_sha256": etag})


def test_etag_equal_to_digest_in_response_refused():
    ok, why = verify_s3_bound_leaf(rec(), s3_client=FakeS3(etag=SHA), **EXP)
    assert (ok, why) == (False, "ETAG_NOT_ACCEPTED_AS_DIGEST")


def test_hash_mismatch_refused():
    s3 = FakeS3({V1: BODY + b"tampered"})
    assert verify_s3_bound_leaf(rec(), s3_client=s3, **EXP) == (False, "S3_PAYLOAD_SHA256_MISMATCH")


def test_unexpected_version_in_response_refused():
    s3 = FakeS3({V1: BODY}, respond_version=V2)
    assert verify_s3_bound_leaf(rec(), s3_client=s3, **EXP) == (False, "S3_UNEXPECTED_VERSION")


@pytest.mark.parametrize("rv", [None, "", "null"])
def test_response_without_version_refused(rv):
    s3 = FakeS3({V1: BODY}, respond_version=rv)
    assert verify_s3_bound_leaf(rec(), s3_client=s3, **EXP) == (False, "S3_RESPONSE_VERSION_MISSING")


def test_newer_version_with_same_bytes_does_not_satisfy_old_binding_of_other_version():
    # Binding names V2 but only V1 exists: NoSuchVersion fails closed; never falls back to latest.
    r = rec(version_id=V2)
    ok, why = verify_s3_bound_leaf(r, s3_client=FakeS3({V1: BODY}), **EXP)
    assert not ok and why.startswith("S3_FETCH_FAILED")


def test_overwritten_latest_version_ignored_bound_version_used():
    s3 = FakeS3({V1: BODY, V2: b"newer content"})
    assert verify_s3_bound_leaf(rec(), s3_client=s3, **EXP) == (True, "OK")
    assert verify_s3_bound_leaf(rec(version_id=V2), s3_client=s3, **EXP) == (False, "S3_PAYLOAD_SHA256_MISMATCH")


@pytest.mark.parametrize("exc", [PermissionError("AccessDenied"), TimeoutError(), RuntimeError("x")])
def test_client_errors_fail_closed(exc):
    ok, why = verify_s3_bound_leaf(rec(), s3_client=FakeS3(raise_exc=exc), **EXP)
    assert not ok and why == f"S3_FETCH_FAILED:{type(exc).__name__}"


@pytest.mark.parametrize("resp", ["not-a-dict", {"VersionId": V1, "Body": "str-body"},
                                  {"VersionId": V1}])
def test_malformed_responses_fail_closed(resp):
    class C:
        def get_object(self, **_):
            return resp
    ok, why = verify_s3_bound_leaf(rec(), s3_client=C(), **EXP)
    assert not ok and why in {"S3_RESPONSE_INVALID", "S3_BODY_INVALID"}


def test_oversize_body_refused(monkeypatch):
    monkeypatch.setattr(apb, "MAX_S3_OBJECT_BYTES", 8)
    assert verify_s3_bound_leaf(rec(), s3_client=FakeS3(), **EXP) == (False, "S3_BODY_TOO_LARGE")


@pytest.mark.parametrize("field,val,reason", [
    ("expected_payload_sha256", "0" * 64, "PAYLOAD_MISMATCH"),
    ("expected_receipt_id", "rcpt:other", "RECEIPT_ID_MISMATCH"),
    ("expected_anchor_id", "anc:other", "ANCHOR_ID_MISMATCH")])
def test_receipt_anchor_payload_substitution_refused(field, val, reason):
    assert verify_s3_bound_leaf(rec(), s3_client=FakeS3(), **{**EXP, field: val}) == (False, reason)


@pytest.mark.parametrize("mut", [
    lambda r: r.update(version_id=V2), lambda r: r.update(key=r["key"] + "x"),
    lambda r: r.update(bucket="sportsedge-other"), lambda r: r.update(receipt_id="rcpt:x"),
    lambda r: r.update(anchor_id="anc:x"), lambda r: r.update(payload_sha256="1" * 64)])
def test_record_field_tamper_breaks_leaf(mut):
    r = rec()
    mut(r)
    assert verify_s3_bound_leaf(r, s3_client=FakeS3(), **EXP)[1] in {"LEAF_MISMATCH", "PAYLOAD_MISMATCH"}


@pytest.mark.parametrize("mut,reason", [
    (lambda r: r.update(domain="SPORTSEDGE_ANCHOR_LEAF_BINDING_V1"), "WRONG_DOMAIN"),
    (lambda r: r.update(carrier="RFC3161_TSA"), "S3_RECORD_SHAPE_INVALID"),
    (lambda r: r.update(extra="x"), "S3_RECORD_SHAPE_INVALID"),
    (lambda r: r.pop("version_id"), "S3_RECORD_SHAPE_INVALID")])
def test_record_shape_refused(mut, reason):
    r = rec()
    mut(r)
    assert verify_s3_bound_leaf(r, s3_client=FakeS3(), **EXP) == (False, reason)


@pytest.mark.parametrize("k,v", [("bucket", "Bad_Bucket"), ("bucket", "a..b-c"), ("key", "/lead"),
                                 ("key", "a/../b"), ("key", "a//b"), ("key", "a\nb"), ("key", ""),
                                 ("receipt_id", "has space"), ("anchor_id", ""),
                                 ("schema", "OTHER_V9"), ("payload_sha256", SHA.upper())])
def test_non_canonical_fields_refused(k, v):
    with pytest.raises(BindingError):
        bind_s3_leaf(**{**BASE, k: v})


# ---- append-only immutable ledger ----

def test_ledger_append_then_admit(tmp_path):
    led = S3BindingLedger(tmp_path / "s3_bindings.jsonl")
    led.append(bind_s3_leaf(**BASE))
    assert admit_s3_bound_payload(rec(), ledger=led, s3_client=FakeS3(), **EXP) == (True, "OK")


def test_ledger_rebind_refused_even_to_new_version(tmp_path):
    led = S3BindingLedger(tmp_path / "l.jsonl")
    led.append(bind_s3_leaf(**BASE))
    with pytest.raises(BindingError, match="S3_BINDING_IMMUTABLE"):
        led.append(bind_s3_leaf(**{**BASE, "version_id": V2}))
    with pytest.raises(BindingError, match="S3_BINDING_IMMUTABLE"):
        led.append(bind_s3_leaf(**BASE))
    assert len(led.entries()) == 1


def test_admit_refuses_binding_not_in_ledger_or_differing(tmp_path):
    led = S3BindingLedger(tmp_path / "l.jsonl")
    assert admit_s3_bound_payload(rec(), ledger=led, s3_client=FakeS3(), **EXP)[1] == "S3_BINDING_NOT_IN_LEDGER"
    led.append(bind_s3_leaf(**BASE))
    s3 = FakeS3({V1: BODY, V2: BODY})
    assert admit_s3_bound_payload(rec(version_id=V2), ledger=led, s3_client=s3, **EXP)[1] \
        == "S3_BINDING_DIFFERS_FROM_LEDGER"


def test_admit_still_verifies_live_object(tmp_path):
    led = S3BindingLedger(tmp_path / "l.jsonl")
    led.append(bind_s3_leaf(**BASE))
    bad = FakeS3({V1: b"swapped"})
    assert admit_s3_bound_payload(rec(), ledger=led, s3_client=bad, **EXP) == (False, "S3_PAYLOAD_SHA256_MISMATCH")


@pytest.mark.parametrize("corrupt", [b"{not json}\n", b'{"domain":"x"}\n', "TORN", b"\xff\xfe\n", "EDIT", "DUP"])
def test_ledger_corruption_fails_closed(tmp_path, corrupt):
    p = tmp_path / "l.jsonl"
    led = S3BindingLedger(p)
    led.append(bind_s3_leaf(**BASE))
    raw = p.read_bytes()
    if corrupt == "TORN":
        p.write_bytes(raw[:-5])
    elif corrupt == "EDIT":
        d = json.loads(raw)
        d["version_id"] = V2          # in-place rewrite of an existing binding
        p.write_bytes((json.dumps(d) + "\n").encode())
    elif corrupt == "DUP":
        p.write_bytes(raw + raw)
    else:
        p.write_bytes(raw + corrupt)
    with pytest.raises(BindingError):
        led.entries()
    ok, why = admit_s3_bound_payload(rec(), ledger=led, s3_client=FakeS3(), **EXP)
    assert not ok and why.startswith("S3_LEDGER")
    with pytest.raises(BindingError):
        led.append(bind_s3_leaf(**{**BASE, "receipt_id": "rcpt:new"}))


def test_ledger_symlink_refused(tmp_path):
    real = tmp_path / "real.jsonl"
    real.write_bytes(b"")
    link = tmp_path / "l.jsonl"
    os.symlink(real, link)
    with pytest.raises(OSError):
        S3BindingLedger(link).append(bind_s3_leaf(**BASE))
    ok, why = admit_s3_bound_payload(rec(), ledger=S3BindingLedger(link), s3_client=FakeS3(), **EXP)
    assert not ok and why.startswith("S3_LEDGER_UNREADABLE")


def test_ledger_rejects_non_leaf_objects(tmp_path):
    with pytest.raises(BindingError):
        S3BindingLedger(tmp_path / "l.jsonl").append(rec())


def test_bound_leaf_is_immutable():
    leaf = bind_s3_leaf(**BASE)
    with pytest.raises(Exception):
        leaf.version_id = V2


def test_s3_leaf_composes_with_tsa_batch_root():
    from sportsedge import evidence_anchor as ea
    assert len(ea.batch_root([bind_s3_leaf(**BASE).leaf])) == 64


def test_no_network_or_aws_dependency():
    src = open(apb.__file__, encoding="utf-8").read()
    assert "import boto3" not in src and "urlopen" not in src
