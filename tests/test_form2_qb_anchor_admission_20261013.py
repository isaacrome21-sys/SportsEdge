"""t127: dual-TSA anchor wired into the Form 2 pinned loader and QB evidence
archive through the shared admission gate.

OFF (committed config): behaviour for every existing anchor source is
unchanged, and the approved quorum anchor is refused with
admission_not_activated. ON is simulated in-process with TEST CAs only.
"""
import hashlib
import json
import shutil

import pytest

from sportsedge import evidence_anchor as ea
from sportsedge.prepricing import qb_form2_pinned_loader as pl
from sportsedge.prepricing.qb_evidence_archive import EvidenceArchiveError, load_archived_form2
from tests.anchor_test_ca import TsaPairForTests, cutoff
from tests.test_cfb_form2_pinned_loader_20261013 import FX, publish
from tests.test_cfb_qb_evidence_archive import setup_archive
from tests.test_cfb_qb_identity_evidence_form2_20261013 import NOW, KICKOFF, CHARTS

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI required")
OFF_REASON = f"{pl.ANCHOR_QUORUM_REFUSED}:admission_not_activated"


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    return TsaPairForTests(tmp_path_factory.mktemp("t127qb"))


def _anchor(pair, digest, leaves=None, **kw):
    b = pair.bundle(leaves or [digest, hashlib.sha256(b"sibling").hexdigest()])
    return pl.ExternalManifestAnchor(digest, pl.QUORUM_ANCHOR_SOURCE, tsa_bundle=b,
                                     event_cutoff=kw.get("event_cutoff", cutoff()))


def _loader(root, anchor):
    return pl.load_form2_bundles_pinned(root, anchor=anchor, verified_fixtures=FX, as_of=NOW)


def _archive(root, manifest, anchor):
    raw = json.dumps(manifest).encode()
    return load_archived_form2(root, anchor=anchor, manifest_bytes=raw,
                               trusted_manifest_sha256=hashlib.sha256(raw).hexdigest(),
                               team_id="48", event_id="401871067", home_team_id="2393",
                               away_team_id="48", kickoff=KICKOFF,
                               previous_game_kickoff=CHARTS["48"][3], as_of=NOW)


def test_flags_off_in_committed_config():
    assert ea.load_config().admission_active is False and not ea.ADMISSION_ACTIVE
    assert pl.APPROVED_ANCHOR_SOURCES == frozenset()


def test_off_loader_refuses_quorum_anchor(tmp_path, pair):
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    m, a = _loader(tmp_path, _anchor(pair, d))
    assert m == {} and a["status"] == OFF_REASON and a["anchor_status"] == "UNANCHORED"


def test_off_existing_sources_unchanged(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    assert _loader(tmp_path, pl.ExternalManifestAnchor(d, "OPERATOR_CONFIG"))[1]["status"] == pl.ANCHOR_SOURCE_NOT_APPROVED
    assert _loader(tmp_path, None)[1]["status"] == pl.NO_EXTERNAL_ANCHOR
    assert _loader(tmp_path, pl.ExternalManifestAnchor(d, "SELF_COMPUTED"))[1]["status"] == pl.ANCHOR_NOT_EXTERNAL


def test_off_quorum_source_without_bundle_still_not_activated(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    a = pl.ExternalManifestAnchor(d, pl.QUORUM_ANCHOR_SOURCE)
    assert _loader(tmp_path, a)[1]["status"] == OFF_REASON


def test_off_archive_refuses_quorum_anchor(tmp_path, pair):
    manifest, _ = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    with pytest.raises(EvidenceArchiveError, match="admission_not_activated"):
        _archive(tmp_path, manifest, _anchor(pair, hashlib.sha256(raw).hexdigest()))


def test_on_loader_admits_research_only(tmp_path, pair, monkeypatch):
    pair.activate(monkeypatch)
    manifest, digest = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    m, a = _loader(tmp_path, _anchor(pair, d))
    assert list(m) == ["48"] and a["status"] == "LOADED" and a["admitted_team_ids"] == ["48"]
    assert a["research_only"] and not (a["eligibility"] or a["staking_allowed"] or a["activation_allowed"])


def test_on_archive_admits(tmp_path, pair, monkeypatch):
    pair.activate(monkeypatch)
    manifest, _ = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    r = _archive(tmp_path, manifest, _anchor(pair, hashlib.sha256(raw).hexdigest()))
    assert r["research_only"] and r["identity_evidence"]["resolved_athlete_id"] == "5153846"


@pytest.mark.parametrize("case,reason", [
    ("uncovered", "anchor_does_not_cover_digest"),
    ("late", "gentime_after_cutoff_minus_margin"),
    ("single", "tsa_quorum_not_met"),
])
def test_on_loader_refusals(tmp_path, pair, monkeypatch, case, reason):
    pair.activate(monkeypatch)
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    if case == "uncovered":
        a = _anchor(pair, d, leaves=[hashlib.sha256(b"other").hexdigest()])
    elif case == "late":
        a = _anchor(pair, d, event_cutoff=cutoff(-1))
    else:
        a = pl.ExternalManifestAnchor(d, pl.QUORUM_ANCHOR_SOURCE,
                                      tsa_bundle=pair.bundle([d], providers=("tsa_a",)),
                                      event_cutoff=cutoff())
    m, au = _loader(tmp_path, a)
    assert m == {} and au["status"] == f"{pl.ANCHOR_QUORUM_REFUSED}:{reason}"
