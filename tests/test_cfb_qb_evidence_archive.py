import hashlib
import json

import pytest

from sportsedge.prepricing.qb_evidence_archive import (
    EvidenceArchiveError, SCHEMA, load_archived_form2,
)
from tests.test_cfb_qb_identity_evidence_form2_20261013 import (
    make_bundle, rechain, NOW, KICKOFF, CHARTS,
)


def setup_archive(tmp_path, mutate_bundle=None, mutate_entry=None):
    bundle = make_bundle("48")
    if mutate_bundle:
        mutate_bundle(bundle)
        rechain(bundle)
    raw = json.dumps(bundle).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / (digest + ".json")).write_bytes(raw)
    entry = dict(team_id="48", event_id="401871067", home_team_id="2393",
                 away_team_id="48", kickoff_utc=KICKOFF.isoformat(),
                 recorded_at_utc="2026-10-13T13:30:00Z", bundle_sha256=digest)
    if mutate_entry:
        mutate_entry(entry)
    manifest = dict(schema=SCHEMA, entries=[entry])
    return manifest, digest


def load(tmp_path, manifest, **overrides):
    raw = json.dumps(manifest).encode()
    args = dict(manifest_bytes=raw, trusted_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                team_id="48", event_id="401871067", home_team_id="2393", away_team_id="48",
                kickoff=KICKOFF, previous_game_kickoff=CHARTS["48"][3], as_of=NOW)
    args.update(overrides)
    return load_archived_form2(tmp_path, **args)


def test_valid_archive_remains_research_only(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    result = load(tmp_path, manifest)
    assert result["identity_evidence"]["resolved_athlete_id"] == "5153846"
    assert result["research_only"]
    assert not any(result[k] for k in ("eligibility", "staking_allowed", "activation_allowed"))
    assert "UNVERIFIED" in result["identity_evidence"]["availability_status"]


def test_adjacent_manifest_cannot_repin_itself(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    pin = hashlib.sha256(json.dumps(manifest).encode()).hexdigest()
    manifest["entries"][0]["recorded_at_utc"] = "2026-10-13T13:29:00Z"
    with pytest.raises(EvidenceArchiveError, match="MANIFEST_HASH_MISMATCH"):
        load(tmp_path, manifest, trusted_manifest_sha256=pin)


def test_resealed_bundle_cannot_replace_archived_bytes(tmp_path):
    manifest, digest = setup_archive(tmp_path)
    path = tmp_path / (digest + ".json")
    b = json.loads(path.read_bytes())
    b["depth_snapshot"]["captured_at_utc"] = "2026-10-13T13:25:00Z"
    rechain(b)
    path.write_text(json.dumps(b))
    with pytest.raises(EvidenceArchiveError, match="BUNDLE_HASH_MISMATCH"):
        load(tmp_path, manifest)


@pytest.mark.parametrize("field,value,reason", [
    ("home_team_id", "48", "FIXTURE_MISMATCH"),
    ("away_team_id", "2393", "FIXTURE_MISMATCH"),
    ("event_id", "wrong", "RECEIPT_NOT_UNIQUE"),
    ("recorded_at_utc", "2026-10-13T14:01:00Z", "NOT_AVAILABLE"),
    ("recorded_at_utc", "2026-10-13T13:00:00Z", "PRECEDES_FETCH"),
    ("recorded_at_utc", "2026-10-13T13:30:00", "TIME_INVALID"),
    ("bundle_sha256", "../../evil", "DIGEST_INVALID"),
])
def test_hostile_receipts(tmp_path, field, value, reason):
    manifest, _ = setup_archive(tmp_path, mutate_entry=lambda e: e.update({field: value}))
    with pytest.raises(EvidenceArchiveError, match=reason):
        load(tmp_path, manifest)


def test_duplicate_receipts_fail_closed(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    manifest["entries"].append(dict(manifest["entries"][0]))
    with pytest.raises(EvidenceArchiveError, match="NOT_UNIQUE"):
        load(tmp_path, manifest)


def test_external_pin_does_not_excuse_semantic_qb_swap(tmp_path):
    def mutate(b):
        b["depth_snapshot"]["qb_order"][0]["name"] = "Braden Streeter"
    manifest, _ = setup_archive(tmp_path, mutate_bundle=mutate)
    with pytest.raises(EvidenceArchiveError, match="BUNDLE_REJECTED"):
        load(tmp_path, manifest)


def test_post_kickoff_reader_refused(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    with pytest.raises(EvidenceArchiveError, match="NOT_PREGAME"):
        load(tmp_path, manifest, as_of=KICKOFF)


def test_duplicate_json_keys_refused_even_when_pinned(tmp_path):
    raw = b'{"schema":"x","schema":"CFB_FORM2_ARCHIVE_MANIFEST_V1","entries":[]}'
    with pytest.raises(EvidenceArchiveError, match="DUPLICATE_JSON_KEY"):
        load(tmp_path, {}, manifest_bytes=raw,
             trusted_manifest_sha256=hashlib.sha256(raw).hexdigest())
