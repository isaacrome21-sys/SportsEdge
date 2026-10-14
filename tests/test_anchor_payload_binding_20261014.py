import hashlib

import pytest

from sportsedge import evidence_anchor as ea
from sportsedge.anchor_payload_binding import (BINDING_DOMAIN, BindingError, bind_leaf,
                                               verify_bound_leaf)

PAY = hashlib.sha256(b"synthetic MLB_RECEIPT_JOURNAL_ANCHOR_V1 payload").hexdigest()
# t141: unversioned S3 locations are refused by bind_leaf (owner ruling); S3 uses bind_s3_leaf.
LOC = "git://github.com/isaacrome21-sys/records/mlb/journal/2026-10-14/seg-0001.jsonl"
S3LOC = "s3://sportsedge-anchor-test/mlb/journal/2026-10-14/seg-0001.jsonl"
S = "MLB_RECEIPT_JOURNAL_ANCHOR_V1"


def _b(**k):
    a = dict(schema=S, payload_sha256=PAY, location=LOC, carrier="RFC3161_TSA")
    a.update(k)
    return bind_leaf(**a)


def test_unbound_payload_digest_is_already_stampable():
    # The TSA layer accepts any lowercase SHA-256 leaf, so the publisher's digest composes as-is.
    assert ea.batch_root([PAY]) and len(ea.batch_root([PAY, _b().leaf])) == 64


def test_leaf_is_deterministic_and_domain_separated():
    assert _b().leaf == _b().leaf
    assert _b().leaf != PAY
    assert _b().as_record()["domain"] == BINDING_DOMAIN


@pytest.mark.parametrize("change", [
    {"location": LOC.replace("seg-0001", "seg-0002")},
    {"location": "https://records.example/mlb/seg-0001.jsonl"},
    {"carrier": "OPENTIMESTAMPS"},
    {"carrier": "GIT_RECORDS_BRANCH"},
    {"payload_sha256": hashlib.sha256(b"other").hexdigest()},
])
def test_location_carrier_payload_each_change_leaf_and_root(change):
    assert _b(**change).leaf != _b().leaf
    assert ea.batch_root([_b(**change).leaf]) != ea.batch_root([_b().leaf])


@pytest.mark.parametrize("bad", [
    {"schema": "MLB_RECEIPT_JOURNAL_ANCHOR_V2"}, {"payload_sha256": PAY.upper()},
    {"payload_sha256": PAY[:-1]}, {"location": LOC + "/"}, {"location": "s3://b/a/../x"},
    {"location": " " + LOC}, {"location": LOC + "?versionId=1"}, {"location": "ftp://x/y"},
    {"carrier": "EMAIL"}, {"carrier": None},
])
def test_non_canonical_inputs_refused(bad):
    with pytest.raises(BindingError):
        _b(**bad)


def test_verify_ok_and_each_substitution_refused():
    rec = _b().as_record()
    ok = dict(expected_payload_sha256=PAY, observed_location=LOC, observed_carrier="RFC3161_TSA")
    assert verify_bound_leaf(rec, **ok) == (True, "OK")
    assert verify_bound_leaf(rec, **{**ok, "observed_location": LOC.replace("0001", "0009")})[1] == "LOCATION_MISMATCH"
    assert verify_bound_leaf(rec, **{**ok, "observed_carrier": "OPENTIMESTAMPS"})[1] == "CARRIER_MISMATCH"
    assert verify_bound_leaf(rec, **{**ok, "expected_payload_sha256": "0" * 64})[1] == "PAYLOAD_MISMATCH"
    assert verify_bound_leaf({**rec, "location": LOC.replace("0001", "0009")}, **ok)[1] == "LEAF_MISMATCH"
    assert verify_bound_leaf({**rec, "domain": "X"}, **ok)[1] == "WRONG_DOMAIN"
    assert verify_bound_leaf("nope", **ok)[1] == "WRONG_DOMAIN"


@pytest.mark.parametrize("bad", [{"location": S3LOC}, {"carrier": "S3_OBJECT_LOCK"}])
def test_unversioned_s3_binding_refused_by_v1(bad):
    with pytest.raises(BindingError, match="S3_REQUIRES_VERSIONED_BINDING"):
        _b(**bad)
