"""t156 Option A: anchored QB archive rejects missing, malformed, tampered and
unanchored evidence. Synthetic test-scoped anchor source only (no real certs)."""
import hashlib
import json

import pytest

from sportsedge.prepricing import qb_form2_pinned_loader as pl
from sportsedge.prepricing.qb_evidence_archive import EvidenceArchiveError, load_archived_form2
from tests.test_cfb_qb_evidence_archive import (  # noqa: F401 (autouse fixture)
    TEST_ANCHOR_SOURCE, _approved_test_anchor, load, setup_archive,
)
from tests.test_cfb_qb_identity_evidence_form2_20261013 import CHARTS, KICKOFF, NOW


def _args(raw, anchor):
    return dict(anchor=anchor, manifest_bytes=raw,
                trusted_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                team_id="48", event_id="401871067", home_team_id="2393", away_team_id="48",
                kickoff=KICKOFF, previous_game_kickoff=CHARTS["48"][3], as_of=NOW)


def test_valid_anchored_evidence_admits_research_only(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    result = load(tmp_path, manifest)
    assert result["research_only"] and not result["eligibility"]


def test_missing_bundle_refused(tmp_path):
    manifest, digest = setup_archive(tmp_path)
    (tmp_path / (digest + ".json")).unlink()
    with pytest.raises(EvidenceArchiveError):
        load(tmp_path, manifest)


@pytest.mark.parametrize("raw", [b"", b"{", b"[]", b'{"schema": 1}', b"\xff\xfe"])
def test_malformed_manifest_refused(tmp_path, raw):
    setup_archive(tmp_path)
    anchor = pl.ExternalManifestAnchor(hashlib.sha256(raw).hexdigest(), TEST_ANCHOR_SOURCE)
    with pytest.raises(EvidenceArchiveError):
        load_archived_form2(tmp_path, **_args(raw, anchor))


def test_tampered_manifest_after_anchoring_refused(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    anchor = pl.ExternalManifestAnchor(hashlib.sha256(raw).hexdigest(), TEST_ANCHOR_SOURCE)
    manifest["entries"][0]["recorded_at_utc"] = "2026-10-13T13:31:00Z"
    tampered = json.dumps(manifest).encode()
    args = _args(tampered, anchor)
    args["trusted_manifest_sha256"] = anchor.sha256
    with pytest.raises(EvidenceArchiveError):
        load_archived_form2(tmp_path, **args)


@pytest.mark.parametrize("anchor", [None, "UNANCHORED", {"sha256": "0" * 64}])
def test_unanchored_evidence_refused(tmp_path, anchor):
    manifest, _ = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    with pytest.raises(EvidenceArchiveError, match="ARCHIVE_ANCHOR_REFUSED"):
        load_archived_form2(tmp_path, **_args(raw, anchor))


def test_unapproved_anchor_source_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset())
    manifest, _ = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    anchor = pl.ExternalManifestAnchor(hashlib.sha256(raw).hexdigest(), TEST_ANCHOR_SOURCE)
    with pytest.raises(EvidenceArchiveError, match="ARCHIVE_ANCHOR_REFUSED"):
        load_archived_form2(tmp_path, **_args(raw, anchor))


def test_no_ungated_loader_entry_point():
    import inspect
    from sportsedge.prepricing import qb_evidence_archive as arch
    sig = inspect.signature(arch.load_archived_form2)
    assert sig.parameters["anchor"].default is inspect.Parameter.empty
