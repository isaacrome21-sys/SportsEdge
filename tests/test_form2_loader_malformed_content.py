"""Malformed pinned archive objects must be audited, never crash the runner."""
import hashlib
import json

import pytest

from sportsedge.prepricing.qb_form2_bundle_loader import load_form2_bundles
from sportsedge.prepricing import qb_evidence_archive as archive
from sportsedge.prepricing import qb_identity_evidence as qe


def _load_pinned_raw(tmp_path, raw):
    # A caller-supplied synthetic pin lets these tests reach the parser and
    # schema checks; an unpinned directory must stop before either check.
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / f"{digest}.json").write_bytes(raw)
    manifest = json.dumps({"schema": archive.SCHEMA, "entries": [
        {"bundle_sha256": digest}]}).encode()
    mapping, audit = load_form2_bundles(
        tmp_path, [], manifest_sha256=hashlib.sha256(manifest).hexdigest(),
        manifest_bytes=manifest)
    assert audit["pin_status"] == "VERIFIED"
    entry = next(e for e in audit["entries"] if e["file"] == f"{digest}.json")
    return mapping, audit, entry


@pytest.mark.parametrize("team", [["bad"], "bad", 42, True])
def test_malformed_team_is_audited_without_crashing(tmp_path, team):
    raw = json.dumps({"team": team, "evidence_class": qe.EVIDENCE_CLASS,
                      "evidence_form": qe.EVIDENCE_FORM}).encode()
    mapping, audit, entry = _load_pinned_raw(tmp_path, raw)
    assert mapping == {}
    assert audit["admitted_team_ids"] == []
    assert entry["disposition"] == "EXCLUDED"
    assert entry["team_id"] is None
    assert entry["reason"] == "BUNDLE_SCHEMA_INCOMPLETE"
    assert entry["detail"] == "TEAM_BINDING_FIELDS_MISSING"


def test_invalid_utf8_is_audited_without_crashing(tmp_path):
    mapping, audit, entry = _load_pinned_raw(tmp_path, b"\xff")
    assert mapping == {}
    assert audit["admitted_team_ids"] == []
    assert entry["disposition"] == "EXCLUDED"
    assert entry["reason"] == "ARCHIVE_JSON_INVALID"
    assert entry["detail"] == "ARCHIVE_STRICT_PARSE_REFUSED"


def test_unpinned_malformed_object_is_refused_before_read(tmp_path, monkeypatch):
    raw = b"\xff"
    (tmp_path / f"{hashlib.sha256(raw).hexdigest()}.json").write_bytes(raw)

    def unexpected_read(*args, **kwargs):
        pytest.fail("an unpinned object must not be read")

    monkeypatch.setattr(archive, "_read_bundle", unexpected_read)
    mapping, audit = load_form2_bundles(tmp_path, [])
    assert mapping == {}
    assert audit["pin_status"] == "ABSENT"
    assert audit["entries"][0]["reason"] == "ARCHIVE_PIN_REQUIRED"
