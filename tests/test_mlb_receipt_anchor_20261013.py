"""External receipt anchor -- ported battery (Part B) + Option A publisher.

The anchor module (`sportsedge/mlb_receipt_anchor.py`) was built on the
held-local receipt-hardening branch as Part B of
`test_mlb_receipt_paired_writes_anchor_20261013.py` (11 tests: 6 Part A
paired-write hostiles + 5 Part B anchor tests). This file ports the five
Part B tests VERBATIM (scaffolding included) onto the surviving
intent-journal tree (#2199 composition), and adds the battery for the
real records-branch publisher (`mlb_receipt_anchor_publisher.py`) built
under the owner's Option A decision (target `records/evidence-anchors`,
daily roll-up).

The six Part A tests are NOT ported: they pin the flock paired-write
mechanism, which the confirmed crash-safety direction keeps fallback-only.
Run against this tree they fail 5 of 6 (the receipt recorder here does
not serialize writers or refuse orphaned raw payloads) -- that is a
pre-existing write-path property of this tree, documented in
ANCHOR_BUILD.md as a finding for the integration lane; it is not caused
by, and cannot be fixed inside, this port.

Publisher tests run against an in-memory fake transport: no network, no
real publication. The flag discipline is asserted with the REAL
publisher: `publish_receipt_anchor` refuses while ANCHORING_ENABLED is
False and the transport records zero pushes.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from sportsedge import mlb_source as ms

T0 = datetime(2026, 10, 13, 16, 0, tzinfo=timezone.utc)
URL = "https://x/api/v1/schedule"


def _record_at(rec, *, url=URL, raw=b"{}", when=T0):
    """Record one receipt with the trusted clock pinned at ``when``."""
    rec.clock = lambda: when  # the recorder-clock assertion rides the fetch start
    with patch.object(ms, "_trusted_now", lambda: when):
        return rec.record(url=url, raw=raw, fetch_started_at=when,
                          received_at=when + timedelta(seconds=1))


# --------------------------------------------------------------------------
# PART B -- external anchor (dark, disabled by default) -- VERBATIM PORT
# --------------------------------------------------------------------------

def _anchor_module():
    from sportsedge import mlb_receipt_anchor as anchor
    return anchor


class _FakePublisher:
    def __init__(self):
        self.published: list[dict] = []

    def publish(self, payload):
        self.published.append(payload)
        return {"published_at_utc": "2026-10-13T17:05:00+00:00",
                "location": "fake://records-branch/mlb_receipt_anchors/anchor.json",
                "anchor_id": payload["anchor_id"]}


def _seed_journal(root: Path, receipts: int = 2):
    rec = ms.MLBSourceCapture(root, clock=lambda: T0)
    for i in range(receipts):
        _record_at(rec, raw=json.dumps({"i": i}).encode(), when=T0 + timedelta(seconds=10 * i))
    return rec


def test_anchor_publication_refused_while_disabled_by_default(tmp_path):
    anchor = _anchor_module()
    assert anchor.ANCHORING_ENABLED is False
    _seed_journal(tmp_path)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHORING_DISABLED"):
        anchor.publish_receipt_anchor(tmp_path, _FakePublisher(),
                                      verifier_now=T0 + timedelta(hours=1))


def test_anchor_prepare_publish_verify_with_fake_publisher(tmp_path, monkeypatch):
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    payload = anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))
    assert payload["anchor_claim"] == "EXISTENCE_BY_GITHUB_PUBLICATION_RECEIPT"
    assert payload["anchored"] is False and payload["external_time_anchor"] is False
    assert payload["journal_last_sequence"] == 2 and payload["journal_entry_count"] == 2
    assert "NOT a cryptographic" in " ".join(payload["honest_limits"])
    monkeypatch.setattr(anchor, "ANCHORING_ENABLED", True)
    fake = _FakePublisher()
    published = anchor.publish_receipt_anchor(tmp_path, fake, verifier_now=T0 + timedelta(hours=1))
    assert fake.published and fake.published[0]["anchor_id"] == payload["anchor_id"]
    assert published["anchored"] is True and published["external_time_anchor"] is True
    result = anchor.verify_receipt_anchor(tmp_path, published, verifier_now=T0 + timedelta(hours=1))
    assert result["anchor_status"] == "MATCHES_LOCAL_JOURNAL"


def test_absent_anchor_is_unanchored_not_an_error(tmp_path):
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    result = anchor.verify_receipt_anchor(tmp_path, None, verifier_now=T0 + timedelta(hours=1))
    assert result["anchor_status"] == "UNANCHORED" and result["external_time_anchor"] is False
    assert len(ms.verify_receipt_journal(tmp_path, verifier_now=T0 + timedelta(hours=1))) == 2


def test_anchor_mismatch_after_journal_extends(tmp_path):
    anchor = _anchor_module()
    rec = _seed_journal(tmp_path)
    payload = anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))
    _record_at(rec, raw=b'{"i":99}', when=T0 + timedelta(seconds=60))
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_MISMATCH"):
        anchor.verify_receipt_anchor(tmp_path, payload, verifier_now=T0 + timedelta(hours=1))


def test_anchor_prepare_fails_closed_on_tampered_journal(tmp_path):
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    journal = tmp_path / ms.RECEIPT_JOURNAL_NAME
    journal.write_bytes(journal.read_bytes()[:-1])  # torn tail
    with pytest.raises(ms.MLBSourceError):
        anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_NO_ENTRIES"):
        anchor.prepare_receipt_anchor(tmp_path / "empty", verifier_now=T0 + timedelta(hours=1))


# --------------------------------------------------------------------------
# Option A records-branch publisher (fake transport; no network)
# --------------------------------------------------------------------------

from sportsedge import mlb_receipt_anchor_publisher as pub  # noqa: E402

PUB_DAY = datetime(2026, 10, 14, 3, 0, tzinfo=timezone.utc)
PAYLOAD_PATH = "anchors/2026-10-14/mlb-receipt-journal.json"


class _FakeTransport:
    """In-memory remote: files at head + a commit log with GitHub-style
    synthetic SHAs/times. Faults: corrupt a path's bytes as it lands;
    drop a path from exactly one push (the lag commit)."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.commits: list[tuple[str, str]] = []  # (sha, time) per push
        self.introduced: dict[str, tuple[str, str]] = {}
        self.pushes: list[dict[str, str]] = []
        self.corrupt_paths: set[str] = set()
        self.drop_plan: dict[int, set[str]] = {}  # push ordinal -> paths to drop
        self._tick = 0

    def _time(self) -> str:
        self._tick += 1
        base = datetime(2026, 10, 14, 3, 10, tzinfo=timezone.utc)
        return (base + timedelta(minutes=self._tick)).isoformat()

    def read_remote_file(self, branch, path):
        return self.files.get(path)

    def read_remote_head(self, branch):
        return self.commits[-1] if self.commits else None

    def list_remote_files(self, branch, prefix):
        return sorted(p for p in self.files if p.startswith(prefix))

    def history_for_path(self, branch, path):
        intro = self.introduced.get(path)
        return [intro] if intro else []

    def push_files(self, branch, files, message):
        applied = dict(files)
        for path in self.drop_plan.pop(len(self.pushes) + 1, set()):
            applied.pop(path, None)
        sha = f"{len(self.commits) + 1:040x}"
        when = self._time()
        for path, content in applied.items():
            data = content.encode()
            if path in self.corrupt_paths:
                data = data + b"CORRUPTED"
            if path not in self.files:
                self.introduced[path] = (sha, when)
            self.files[path] = data
        self.commits.append((sha, when))
        self.pushes.append(dict(files))


def _init_series(transport: _FakeTransport):
    transport.push_files(pub.ANCHOR_BRANCH, {
        pub.README_PATH: pub.build_series_readme(),
        pub.CADENCE_PATH: pub.build_series_cadence(),
        pub.INDEX_PATH: json.dumps(pub.empty_index(), sort_keys=True, indent=2) + "\n",
    }, "anchor series: init")


def _publisher(transport: _FakeTransport) -> pub.RecordsBranchPublisher:
    return pub.RecordsBranchPublisher(transport, clock=lambda: PUB_DAY)


def _payload(tmp_path) -> dict:
    anchor = _anchor_module()
    _seed_journal(tmp_path)
    return anchor.prepare_receipt_anchor(tmp_path, verifier_now=T0 + timedelta(hours=1))


def test_module_entrypoint_refuses_with_real_publisher_while_flag_false(tmp_path):
    transport = _FakeTransport()
    _init_series(transport)
    commits_before = len(transport.commits)
    _seed_journal(tmp_path)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHORING_DISABLED"):
        _anchor_module().publish_receipt_anchor(
            tmp_path, _publisher(transport), verifier_now=T0 + timedelta(hours=1))
    assert len(transport.commits) == commits_before  # zero publication attempts


def test_publisher_round_trip_through_module(tmp_path, monkeypatch):
    anchor = _anchor_module()
    transport = _FakeTransport()
    _init_series(transport)
    payload = _payload(tmp_path)
    monkeypatch.setattr(anchor, "ANCHORING_ENABLED", True)
    published = anchor.publish_receipt_anchor(
        tmp_path, _publisher(transport), verifier_now=T0 + timedelta(hours=1))
    assert published["anchored"] is True and published["external_time_anchor"] is True
    receipt = published["publication"]
    assert receipt["anchor_id"] == payload["anchor_id"]
    # Payload bytes on the "remote" are the canonical serialization of
    # the payload the module prepared for publication: same identity
    # (prepared_at_utc is the preparer's clock, not an identity field,
    # so two preparations of one journal state share an anchor_id).
    landed_payload = json.loads(transport.files[PAYLOAD_PATH])
    assert landed_payload["anchor_id"] == payload["anchor_id"]
    for field in ("receipt_chain_head_sha256", "journal_genesis_sha256",
                  "journal_first_sequence", "journal_last_sequence",
                  "journal_entry_count", "journal_sha256"):
        assert landed_payload[field] == payload[field]
    assert transport.files[PAYLOAD_PATH] == pub.canonical_payload_bytes(landed_payload)
    # Index entry names the same introducing commit the receipt does.
    index = json.loads(transport.files[pub.INDEX_PATH])
    (entry,) = [e for e in index["entries"] if e["anchor_id"] == payload["anchor_id"]]
    assert entry["path"] == PAYLOAD_PATH
    assert entry["publication"]["commit_sha"] == receipt["commit_sha"]
    assert entry["publication"]["published_at_utc"] == receipt["published_at_utc"]
    assert receipt["commit_sha"] in receipt["location"] and PAYLOAD_PATH in receipt["location"]


def test_publisher_remote_mismatch_fails_without_retry_or_edit(tmp_path):
    transport = _FakeTransport()
    _init_series(transport)
    transport.corrupt_paths.add(PAYLOAD_PATH)
    payload = _payload(tmp_path)
    before = pub.canonical_payload_bytes(payload)
    pushes_before = len(transport.pushes)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_PUBLICATION_REMOTE_MISMATCH"):
        _publisher(transport).publish(payload)
    assert len(transport.pushes) == pushes_before + 1  # one attempt, no quiet retry
    assert pub.canonical_payload_bytes(payload) == before  # payload never edited


def test_publisher_index_lag_incomplete_then_recovers(tmp_path):
    transport = _FakeTransport()
    _init_series(transport)
    payload = _payload(tmp_path)
    publisher = _publisher(transport)
    # Push ordinals: 1 = series init, 2 = payload commit, 3 = index lag
    # commit. Drop the index from the lag commit only.
    transport.drop_plan[3] = {pub.INDEX_PATH}
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_PUBLICATION_INDEX_INCOMPLETE"):
        publisher.publish(payload)
    introducing_sha = transport.introduced[PAYLOAD_PATH][0]
    receipt = publisher.publish(payload)  # recovery completes the index
    assert receipt["commit_sha"] == introducing_sha  # original commit, payload not re-committed
    index = json.loads(transport.files[pub.INDEX_PATH])
    (entry,) = [e for e in index["entries"] if e["anchor_id"] == payload["anchor_id"]]
    assert entry["publication"]["commit_sha"] == introducing_sha


def test_publisher_idempotent_republish(tmp_path):
    transport = _FakeTransport()
    _init_series(transport)
    payload = _payload(tmp_path)
    publisher = _publisher(transport)
    first = publisher.publish(payload)
    commits_after_first = len(transport.commits)
    second = publisher.publish(payload)
    assert second["already_anchored"] is True
    assert second["published_at_utc"] == first["published_at_utc"]
    assert second["commit_sha"] == first["commit_sha"]
    assert len(transport.commits) == commits_after_first  # no new commits


def test_publisher_refuses_anchor_id_tamper(tmp_path):
    transport = _FakeTransport()
    _init_series(transport)
    payload = _payload(tmp_path)
    payload["journal_entry_count"] = 99  # content no longer matches anchor_id
    pushes_before = len(transport.pushes)
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_PUBLISHER_ANCHOR_ID_INVALID"):
        _publisher(transport).publish(payload)
    assert len(transport.pushes) == pushes_before


def test_publisher_refuses_unknown_schema(tmp_path):
    transport = _FakeTransport()
    _init_series(transport)
    payload = _payload(tmp_path)
    payload["schema"] = "SOME_OTHER_ANCHOR_V9"
    with pytest.raises(ms.MLBSourceError, match="RECEIPT_ANCHOR_PUBLISHER_SCHEMA_UNSUPPORTED"):
        _publisher(transport).publish(payload)


def test_series_artifacts_carry_honest_limits():
    readme = pub.build_series_readme()
    assert "UNANCHORED" in readme and "existence-by-publication-time" in readme
    assert "no promotion authority" in readme.lower() or "authorizes no activation" in readme
    cadence = pub.build_series_cadence()
    assert "daily roll-up" in cadence and "Never backfill" in cadence
    index = pub.empty_index()
    assert index["schema"] == pub.INDEX_SCHEMA and index["entries"] == []
