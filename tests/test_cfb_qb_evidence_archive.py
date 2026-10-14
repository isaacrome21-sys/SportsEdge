import hashlib
import json

import pytest

from sportsedge.prepricing.qb_evidence_archive import (
    EvidenceArchiveError, SCHEMA, load_archived_form2,
)
from tests.test_cfb_qb_identity_evidence_form2_20261013 import (
    make_bundle, rechain, NOW, KICKOFF, CHARTS,
)
from sportsedge.prepricing import qb_form2_pinned_loader as _pl

TEST_ANCHOR_SOURCE = "TEST_ONLY_EXTERNAL_PIN"


@pytest.fixture(autouse=True)
def _approved_test_anchor(monkeypatch):
    # Admission now requires an approved external anchor (hardening 2026-10-13).
    monkeypatch.setattr(_pl, "APPROVED_ANCHOR_SOURCES", frozenset({TEST_ANCHOR_SOURCE}))


def freeze_clock(monkeypatch, when):
    import time as _t
    monkeypatch.setattr(_t, "time_ns", lambda: int(when.timestamp() * 1_000_000_000))


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
    if "anchor" not in args:
        pin = args["trusted_manifest_sha256"]
        try:
            args["anchor"] = _pl.ExternalManifestAnchor(pin, TEST_ANCHOR_SOURCE)
        except ValueError:
            args["anchor"] = None
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


def test_symlink_bundle_refused_even_when_content_matches(tmp_path):
    manifest, digest = setup_archive(tmp_path)
    original = tmp_path / (digest + ".json")
    target = tmp_path / "elsewhere.json"
    original.rename(target)
    original.symlink_to(target)
    with pytest.raises(EvidenceArchiveError, match="UNREADABLE"):
        load(tmp_path, manifest)


def test_symlink_root_refused(tmp_path):
    root = tmp_path / "archive"
    root.mkdir()
    manifest, _ = setup_archive(root)
    link = tmp_path / "redirect"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(EvidenceArchiveError, match="UNREADABLE"):
        load(link, manifest)


def test_fifo_refused_without_waiting_for_writer(tmp_path):
    import os
    manifest, digest = setup_archive(tmp_path)
    path = tmp_path / (digest + ".json")
    path.unlink()
    os.mkfifo(path)
    with pytest.raises(EvidenceArchiveError, match="NOT_REGULAR"):
        load(tmp_path, manifest)


def test_oversized_bundle_refused_before_read(tmp_path, monkeypatch):
    from sportsedge.prepricing import qb_evidence_archive as archive
    manifest, _ = setup_archive(tmp_path)
    monkeypatch.setattr(archive, "MAX_BUNDLE_BYTES", 16)
    with pytest.raises(EvidenceArchiveError, match="BUNDLE_TOO_LARGE"):
        load(tmp_path, manifest)


def test_oversized_manifest_refused(tmp_path, monkeypatch):
    from sportsedge.prepricing import qb_evidence_archive as archive
    manifest, _ = setup_archive(tmp_path)
    monkeypatch.setattr(archive, "MAX_MANIFEST_BYTES", 16)
    with pytest.raises(EvidenceArchiveError, match="MANIFEST_TOO_LARGE"):
        load(tmp_path, manifest)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_json_refused(tmp_path, constant):
    raw = ('{"schema":"' + SCHEMA + '","entries":[],"extra":' + constant + '}').encode()
    with pytest.raises(EvidenceArchiveError, match="NONFINITE"):
        load(tmp_path, {}, manifest_bytes=raw,
             trusted_manifest_sha256=hashlib.sha256(raw).hexdigest())


def test_excessively_nested_json_returns_named_failure(tmp_path):
    depth = 70
    raw = b'[' * depth + b'0' + b']' * depth
    with pytest.raises(EvidenceArchiveError, match="JSON_TOO_DEEP"):
        load(tmp_path, {}, manifest_bytes=raw,
             trusted_manifest_sha256=hashlib.sha256(raw).hexdigest())


def preserve(tmp_path, monkeypatch=None, when=NOW, **overrides):
    import time as _t
    from sportsedge.prepricing.qb_evidence_archive import preserve_form2_bundle
    args = dict(bundle_bytes=json.dumps(make_bundle("48")).encode(),
                team_id="48", event_id="401871067", home_team_id="2393", away_team_id="48",
                kickoff=KICKOFF, previous_game_kickoff=CHARTS["48"][3])
    args.update(overrides)
    original = _t.time_ns
    _t.time_ns = (when if callable(when) else (lambda: int(when.timestamp() * 1_000_000_000)))
    try:
        return preserve_form2_bundle(tmp_path, **args)
    finally:
        _t.time_ns = original


def test_writer_round_trip_is_explicitly_unanchored(tmp_path):
    result = preserve(tmp_path)
    assert result["anchor_status"] == "UNANCHORED"
    assert not result["eligibility"]
    assert (tmp_path / (result["candidate_manifest_sha256"] + ".json")).read_bytes() == result["manifest_bytes"]
    assert load(tmp_path, json.loads(result["manifest_bytes"]))["identity_evidence"]["ok"]
    assert not list(tmp_path.glob(".pending-*"))


def test_writer_retries_preserve_existing_bytes(tmp_path):
    first = preserve(tmp_path)
    paths = {p.name: (p.stat().st_ino, p.read_bytes()) for p in tmp_path.iterdir()}
    assert preserve(tmp_path) == first
    assert paths == {p.name: (p.stat().st_ino, p.read_bytes()) for p in tmp_path.iterdir()}


def test_writer_refuses_corrupt_existing_object(tmp_path):
    raw = json.dumps(make_bundle("48")).encode()
    path = tmp_path / (hashlib.sha256(raw).hexdigest() + ".json")
    path.write_bytes(b"prior evidence")
    with pytest.raises(EvidenceArchiveError, match="EXISTING_OBJECT_MISMATCH"):
        preserve(tmp_path)
    assert path.read_bytes() == b"prior evidence"
    assert [p for p in tmp_path.iterdir() if not p.name.startswith(".pair-intent-")] == [path]


def test_writer_records_time_after_bundle_durability(tmp_path):
    raw = json.dumps(make_bundle("48")).encode()
    path = tmp_path / (hashlib.sha256(raw).hexdigest() + ".json")
    def clock():
        if path.exists():
            assert path.read_bytes() == raw
        return int(NOW.timestamp() * 1_000_000_000)
    calls = []
    def tracking():
        calls.append(path.exists())
        return clock()
    preserve(tmp_path, when=tracking)
    # Recorded time sampled (at least once) after the bundle was durable.
    assert True in calls


def test_writer_failed_validation_never_publishes_manifest(tmp_path):
    with pytest.raises(EvidenceArchiveError, match="NOT_PREGAME"):
        preserve(tmp_path, when=KICKOFF)
    # orphan bundle + leftover pair intent (detectable), no success receipt
    names = sorted(p.name for p in tmp_path.iterdir())
    assert len(names) == 2 and names[0].startswith(".pair-intent-")


def test_writer_failed_fsync_never_publishes_partial_file(tmp_path, monkeypatch):
    import os
    def fail(fd):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="disk failure"):
        preserve(tmp_path)
    assert not list(tmp_path.iterdir())
