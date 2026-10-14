"""Malformed local inputs must produce exclusions, never crash the runner."""
import hashlib
import json

import pytest

from sportsedge.prepricing.qb_form2_bundle_loader import load_form2_bundles
from sportsedge.prepricing import qb_evidence_archive as archive


@pytest.mark.parametrize("team", [["bad"], "bad", 42, True])
def test_malformed_team_is_audited_without_crashing(tmp_path, team):
    (tmp_path / "bundle.json").write_text(json.dumps({"team": team}))
    mapping, audit = load_form2_bundles(tmp_path, [])
    assert mapping == {}
    assert audit["admitted_team_ids"] == []
    assert audit["entries"][0]["disposition"] == "EXCLUDED"
    assert audit["entries"][0]["team_id"] is None


def test_invalid_utf8_is_audited_without_crashing(tmp_path):
    """Preserve legacy UTF-8 refusal under the newer external-pin contract.

    No pin must refuse before reading any input. A synthetically pinned
    content-addressed invalid-UTF8 object must be EXCLUDED by the strict
    archive parser rather than crashing or entering the Form 2 mapping.
    """
    raw = b"\xff"
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / (digest + ".json")).write_bytes(raw)

    mapping, unpinned = load_form2_bundles(tmp_path, [])
    assert mapping == {}
    assert unpinned["admitted_team_ids"] == []
    assert unpinned["pin_status"] == "ABSENT"
    assert unpinned["entries"][0]["reason"] == "ARCHIVE_PIN_REQUIRED"

    manifest_bytes = json.dumps({"schema": archive.SCHEMA, "entries": []}).encode()
    manifest_pin = hashlib.sha256(manifest_bytes).hexdigest()
    mapping, audit = load_form2_bundles(
        tmp_path, [], manifest_sha256=manifest_pin,
        manifest_bytes=manifest_bytes)
    assert mapping == {}
    assert audit["admitted_team_ids"] == []
    assert audit["pin_status"] == "VERIFIED"
    bad = [e for e in audit["entries"] if e.get("file_name") == digest + ".json"]
    assert len(bad) == 1
    assert bad[0]["disposition"] == "EXCLUDED"
    assert bad[0]["reason"] == "ARCHIVE_JSON_INVALID"
    assert bad[0]["detail"] == "ARCHIVE_STRICT_PARSE_REFUSED"
