"""Offline contracts for the owner receipt format.

The owner envelope (sportsedge/backtest/receipt_format.py) binds
an immutable payload to two distinct instants — observation and
EFFECTIVE AVAILABILITY — with the effective time assertable only
as early as its stated basis supports. These tests prove the
fail-closed rules:

  * payload hash mismatch / paraphrased payload copy -> invalid;
  * missing effective time or basis -> invalid;
  * effective after observed -> invalid;
  * payload-carried bases (SOURCE_TIMESTAMP / FEED_PUBLICATION)
    pin the effective time to the value the payload itself
    carries — earlier is fabrication, later is a different claim;
  * OBSERVED_FIRST_SEEN pins the effective time to the
    observation instant exactly;
  * corrections are append-only supersede references, never
    edits, and currency is derived by walking the chain;
  * stored envelopes are write-once and re-validate from disk,
    hash re-verified.

Nothing here prices anything, activates anything, or certifies
evidence quality — an envelope attests provenance only.
"""
import base64
import copy
import hashlib
import json

import pytest

from sportsedge.backtest import receipt_format as rf

SOURCE_STAMP = "2026-10-10T15:00:00Z"
PUBLISHED_STAMP = "2026-10-10T14:30:00Z"
OBSERVED = "2026-10-10T18:00:00Z"


def make_payload(**overrides):
    payload = {
        "qb_designation": "OUT",
        "source_timestamp_utc": SOURCE_STAMP,
        "published_at_utc": PUBLISHED_STAMP,
    }
    payload.update(overrides)
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def build(**overrides):
    kwargs = {
        "fixture_id": "nfl:2026-10-11:Kansas City Chiefs:Buffalo Bills",
        "participants": [{"participant_id": "player:gsis-00-0034796",
                          "role": "QB"}],
        "observed_at": OBSERVED,
        "effective_at": SOURCE_STAMP,
        "effective_at_basis": rf.BASIS_SOURCE_TIMESTAMP,
        "effective_at_basis_field": "source_timestamp_utc",
        "provenance": {"source_name": "TEST_FEED",
                       "retrieval_path": "offline test fixture"},
    }
    kwargs.update(overrides)
    return rf.build_owner_receipt(make_payload(), **kwargs)


def test_valid_envelope_builds_and_id_is_content_derived():
    env_a = build()
    env_b = build()  # different issuance instant, same content
    assert env_a["envelope_id"] == env_b["envelope_id"]
    assert env_a["payload_sha256"] == hashlib.sha256(
        make_payload()).hexdigest()
    assert rf.payload_bytes_of(env_a) == make_payload()
    assert rf.validate_owner_receipt(env_a) is env_a


def test_payload_tamper_breaks_hash_binding():
    env = build()
    forged = copy.deepcopy(env)
    forged["raw_payload"] = base64.b64encode(
        make_payload(qb_designation="QUESTIONABLE")).decode("ascii")
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        rf.validate_owner_receipt(forged)
    assert "OWNER_PAYLOAD_HASH_MISMATCH" in str(excinfo.value)


def test_paraphrased_payload_copy_is_invalid():
    env = build()
    forged = copy.deepcopy(env)
    forged["payload_json"] = dict(forged["payload_json"],
                                  qb_designation="QUESTIONABLE")
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        rf.validate_owner_receipt(forged)
    assert "OWNER_PAYLOAD_JSON_MISMATCH" in str(excinfo.value)


def test_missing_effective_at_is_invalid():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at=None)
    assert "OWNER_EFFECTIVE_AT_MISSING" in str(excinfo.value)


def test_missing_basis_is_invalid():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at_basis=None)
    assert "OWNER_EFFECTIVE_AT_BASIS_MISSING" in str(excinfo.value)


def test_unknown_basis_is_invalid():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at_basis="WHEN_WE_GOT_AROUND_TO_IT")
    assert "OWNER_EFFECTIVE_AT_BASIS_INVALID" in str(excinfo.value)


def test_effective_after_observed_is_invalid():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at="2026-10-10T19:00:00Z",
              effective_at_basis=rf.BASIS_OBSERVED_FIRST_SEEN,
              effective_at_basis_field=None)
    assert "OWNER_EFFECTIVE_AFTER_OBSERVED" in str(excinfo.value)


def test_source_timestamp_basis_pins_effective_to_payload():
    # Asserting availability EARLIER than the source's own stamp
    # is exactly the fabrication the basis rule exists to refuse.
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at="2026-10-10T14:00:00Z")
    assert "OWNER_EFFECTIVE_AT_BASIS_MISMATCH" in str(excinfo.value)
    # Later than the payload carries is a different claim, too.
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at="2026-10-10T16:00:00Z")
    assert "OWNER_EFFECTIVE_AT_BASIS_MISMATCH" in str(excinfo.value)


def test_source_timestamp_basis_requires_payload_field():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at_basis_field=None)
    assert "OWNER_EFFECTIVE_BASIS_FIELD_MISSING" in str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at_basis_field="no_such_field")
    assert "OWNER_EFFECTIVE_BASIS_FIELD_ABSENT_FROM_PAYLOAD" in \
        str(excinfo.value)


def test_feed_publication_basis_pins_to_publication_stamp():
    env = build(effective_at=PUBLISHED_STAMP,
                effective_at_basis=rf.BASIS_FEED_PUBLICATION,
                effective_at_basis_field="published_at_utc")
    assert env["effective_at_utc"] == PUBLISHED_STAMP
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at=SOURCE_STAMP,
              effective_at_basis=rf.BASIS_FEED_PUBLICATION,
              effective_at_basis_field="published_at_utc")
    assert "OWNER_EFFECTIVE_AT_BASIS_MISMATCH" in str(excinfo.value)


def test_first_seen_basis_pins_effective_to_observation():
    env = build(effective_at=OBSERVED,
                effective_at_basis=rf.BASIS_OBSERVED_FIRST_SEEN,
                effective_at_basis_field=None)
    assert env["effective_at_utc"] == OBSERVED
    # An earlier effective time is unprovable under first-seen.
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at=SOURCE_STAMP,
              effective_at_basis=rf.BASIS_OBSERVED_FIRST_SEEN,
              effective_at_basis_field=None)
    assert "OWNER_EFFECTIVE_FIRST_SEEN_MISMATCH" in \
        str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(effective_at=OBSERVED,
              effective_at_basis=rf.BASIS_OBSERVED_FIRST_SEEN,
              effective_at_basis_field="source_timestamp_utc")
    assert "OWNER_EFFECTIVE_BASIS_FIELD_UNEXPECTED" in \
        str(excinfo.value)


def test_naive_timestamps_are_invalid():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(observed_at="2026-10-10T18:00:00")
    assert "OWNER_TIMESTAMP_NOT_UTC_AWARE" in str(excinfo.value)


def test_identity_and_provenance_are_required():
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(fixture_id="  ")
    assert "OWNER_FIXTURE_ID_MISSING" in str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(participants=[])
    assert "OWNER_PARTICIPANTS_MISSING" in str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(participants=[{"role": "QB"}])
    assert "OWNER_PARTICIPANT_ID_MISSING" in str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(provenance={"retrieval_path": "x"})
    assert "OWNER_PROVENANCE_SOURCE_NAME_MISSING" in \
        str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        build(provenance={"source_name": "x"})
    assert "OWNER_PROVENANCE_RETRIEVAL_PATH_MISSING" in \
        str(excinfo.value)


def test_correction_is_a_new_envelope_never_an_edit(tmp_path):
    original = build()
    path, dup = rf.write_owner_receipt(tmp_path, original)
    assert not dup
    before = path.read_bytes()
    corrected = rf.build_correction(
        original, make_payload(qb_designation="QUESTIONABLE"),
        reason="source issued a corrected designation",
        fixture_id=original["fixture_id"],
        participants=original["participants"],
        observed_at="2026-10-10T19:00:00Z",
        effective_at=SOURCE_STAMP,
        effective_at_basis=rf.BASIS_SOURCE_TIMESTAMP,
        effective_at_basis_field="source_timestamp_utc",
        provenance=original["provenance"])
    assert corrected["envelope_id"] != original["envelope_id"]
    assert corrected["corrections"][-1] == {
        "supersedes_envelope_id": original["envelope_id"],
        "reason": "source issued a corrected designation"}
    # The original file is byte-identical and still validates.
    assert path.read_bytes() == before
    assert rf.read_owner_receipt(path)["envelope_id"] == \
        original["envelope_id"]
    both = [original, corrected]
    assert rf.chain_status(original["envelope_id"], both) == \
        "SUPERSEDED"
    assert rf.chain_status(corrected["envelope_id"], both) == \
        "CURRENT"
    assert rf.chain_status("ownr_missing", both) == "UNKNOWN"


def test_correction_self_reference_and_missing_reason_refused():
    env = build()
    forged = copy.deepcopy(env)
    forged["corrections"] = [
        {"supersedes_envelope_id": env["envelope_id"],
         "reason": "loop"}]
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        rf.validate_owner_receipt(forged)
    assert "OWNER_CORRECTION_SELF_REFERENCE" in str(excinfo.value)
    with pytest.raises(rf.OwnerReceiptError) as excinfo:
        rf.build_correction(
            env, make_payload(), reason="  ",
            fixture_id=env["fixture_id"],
            participants=env["participants"], observed_at=OBSERVED,
            effective_at=SOURCE_STAMP,
            effective_at_basis=rf.BASIS_SOURCE_TIMESTAMP,
            effective_at_basis_field="source_timestamp_utc",
            provenance=env["provenance"])
    assert "OWNER_CORRECTION_REASON_MISSING" in str(excinfo.value)


def test_write_once_roundtrip_and_duplicate(tmp_path):
    env = build()
    path, dup = rf.write_owner_receipt(tmp_path, env)
    assert not dup and path.is_file()
    assert rf.read_owner_receipt(path) == env
    # Re-issuance of the same attested content is a duplicate,
    # never a second file and never an overwrite.
    path2, dup2 = rf.write_owner_receipt(tmp_path, build())
    assert dup2 and path2 == path
    assert len(rf.list_owner_receipts(tmp_path)) == 1
    # A tampered store fails validation on read, hash first.
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["fixture_id"] = "nfl:elsewhere"
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(rf.OwnerReceiptError):
        rf.read_owner_receipt(path)
