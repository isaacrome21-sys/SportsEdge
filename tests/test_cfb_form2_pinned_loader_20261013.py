"""Pinned Form 2 loader (Grok reimplementation, 2026-10-13)."""
import hashlib
import json
import os

import pytest

from sportsedge.prepricing import qb_form2_pinned_loader as pl
from sportsedge.prepricing.qb_evidence_archive import SCHEMA
from tests.test_cfb_qb_evidence_archive import setup_archive
from tests.test_cfb_qb_identity_evidence_form2_20261013 import NOW, KICKOFF, CHARTS

SRC = "TEST_ONLY_EXTERNAL_PIN"
FX = {"48": dict(event_id="401871067", home_team_id="2393", away_team_id="48",
                 kickoff=KICKOFF, previous_game_kickoff=CHARTS["48"][3])}


def publish(root, manifest):
    raw = json.dumps(manifest).encode()
    digest = hashlib.sha256(raw).hexdigest()
    (root / (digest + ".json")).write_bytes(raw)
    return digest


@pytest.fixture
def approved(monkeypatch):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset({SRC}))


def run(root, anchor, fixtures=FX):
    return pl.load_form2_bundles_pinned(root, anchor=anchor, verified_fixtures=fixtures, as_of=NOW)


def test_default_no_anchor_source_approved_admission_impossible(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    assert pl.APPROVED_ANCHOR_SOURCES == frozenset()
    m, a = run(tmp_path, pl.ExternalManifestAnchor(d, "OPERATOR_CONFIG"))
    assert m == {} and a["status"] == pl.ANCHOR_SOURCE_NOT_APPROVED
    m, a = run(tmp_path, None)
    assert m == {} and a["status"] == pl.NO_EXTERNAL_ANCHOR and "impossible" in a["detail"]


@pytest.mark.parametrize("anchor", ["a" * 64, {"sha256": "a" * 64}, 5, b"x"])
def test_untyped_or_self_computed_digests_refused(tmp_path, approved, anchor):
    m, a = run(tmp_path, anchor)
    assert m == {} and a["status"] == pl.ANCHOR_NOT_EXTERNAL


@pytest.mark.parametrize("src", ["SELF_COMPUTED", "candidate", " UNANCHORED ", ""])
def test_self_computed_source_labels_refused(tmp_path, monkeypatch, src):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset({src}))
    m, a = run(tmp_path, pl.ExternalManifestAnchor("a" * 64, src))
    assert a["status"] == pl.ANCHOR_NOT_EXTERNAL


def test_subclass_anchor_refused(tmp_path, approved):
    class Fake(pl.ExternalManifestAnchor):
        pass
    assert run(tmp_path, Fake("a" * 64, SRC))[1]["status"] == pl.ANCHOR_NOT_EXTERNAL


@pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "../" + "a" * 61, None])
def test_anchor_digest_validated(bad):
    with pytest.raises(ValueError):
        pl.ExternalManifestAnchor(bad, SRC)


def test_valid_pinned_archive_admits_research_only(tmp_path, approved):
    manifest, digest = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    m, a = run(tmp_path, pl.ExternalManifestAnchor(d, SRC))
    assert list(m) == ["48"] and a["admitted_team_ids"] == ["48"]
    assert a["entries"][0]["bundle_sha256"] == digest
    assert a["research_only"] and not (a["eligibility"] or a["staking_allowed"] or a["activation_allowed"])


def test_unverified_fixture_excluded(tmp_path, approved):
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    m, a = run(tmp_path, pl.ExternalManifestAnchor(d, SRC), fixtures={})
    assert m == {} and a["entries"][0]["reason"] == pl.FIXTURE_UNVERIFIED


def test_wrong_pin_mismatch(tmp_path, approved):
    manifest, _ = setup_archive(tmp_path)
    publish(tmp_path, manifest)
    m, a = run(tmp_path, pl.ExternalManifestAnchor("b" * 64, SRC))
    assert m == {} and a["status"] == "ARCHIVE_BUNDLE_UNREADABLE"


@pytest.mark.parametrize("dup", ["team", "bundle"])
def test_whole_intake_duplicate_refusal(tmp_path, approved, dup):
    manifest, _ = setup_archive(tmp_path)
    e2 = dict(manifest["entries"][0])
    if dup == "team":
        e2["event_id"] = "999"; e2["bundle_sha256"] = "c" * 64
    else:
        e2["team_id"] = "2393"
    manifest["entries"].append(e2)
    d = publish(tmp_path, manifest)
    m, a = run(tmp_path, pl.ExternalManifestAnchor(d, SRC),
               fixtures={**FX, "2393": FX["48"]})
    assert m == {} and a["status"] == pl.WHOLE_INTAKE_DUPLICATE and a["entries"] == []


def test_symlinked_root_refused(tmp_path, approved):
    real = tmp_path / "real"; real.mkdir()
    manifest, _ = setup_archive(real)
    d = publish(real, manifest)
    link = tmp_path / "link"; os.symlink(real, link)
    assert run(link, pl.ExternalManifestAnchor(d, SRC))[1]["status"] == pl.ROOT_UNSAFE


@pytest.mark.parametrize("root", ["relative/dir", "/tmp/../tmp", None, 7, "/nonexistent/x"])
def test_unsafe_root_paths_refused(approved, root):
    assert run(root, pl.ExternalManifestAnchor("a" * 64, SRC))[1]["status"] == pl.ROOT_UNSAFE


def test_regular_file_root_refused(tmp_path, approved):
    f = tmp_path / "f"; f.write_text("x")
    assert run(f, pl.ExternalManifestAnchor("a" * 64, SRC))[1]["status"] == pl.ROOT_UNSAFE


def test_symlinked_manifest_refused(tmp_path, approved):
    manifest, _ = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    d = hashlib.sha256(raw).hexdigest()
    other = tmp_path / "elsewhere"; other.write_bytes(raw)
    os.symlink(other, tmp_path / (d + ".json"))
    assert run(tmp_path, pl.ExternalManifestAnchor(d, SRC))[1]["status"] == "ARCHIVE_BUNDLE_UNREADABLE"


def test_fifo_manifest_refused(tmp_path, approved):
    d = "d" * 64
    os.mkfifo(tmp_path / (d + ".json"))
    assert run(tmp_path, pl.ExternalManifestAnchor(d, SRC))[1]["status"] == "ARCHIVE_BUNDLE_NOT_REGULAR"


def test_oversize_manifest_refused(tmp_path, approved):
    raw = b'{"schema":"' + SCHEMA.encode() + b'","entries":[],"pad":"' + b"x" * (1024 * 1024) + b'"}'
    d = hashlib.sha256(raw).hexdigest()
    (tmp_path / (d + ".json")).write_bytes(raw)
    assert run(tmp_path, pl.ExternalManifestAnchor(d, SRC))[1]["status"] == "ARCHIVE_MANIFEST_TOO_LARGE"


@pytest.mark.parametrize("body", [b"[]", b'{"schema":"X","entries":[]}', b'{"schema":"%s","entries":[1]}' % SCHEMA.encode(),
                                  b"not json", b'{"a":1,"a":2}', b'{"x":NaN}'])
def test_malformed_manifest_refused(tmp_path, approved, body):
    d = hashlib.sha256(body).hexdigest()
    (tmp_path / (d + ".json")).write_bytes(body)
    m, a = run(tmp_path, pl.ExternalManifestAnchor(d, SRC))
    assert m == {} and a["status"].startswith("ARCHIVE_")


@pytest.mark.parametrize("fx", [{"48": "x"}, {"48": {}}, {"48": {"event_id": None}},
                                {"48": dict(FX["48"], kickoff="garbage")},
                                {"48": dict(FX["48"], event_id="other")}])
def test_wrong_type_fixtures_never_crash(tmp_path, approved, fx):
    manifest, _ = setup_archive(tmp_path)
    d = publish(tmp_path, manifest)
    m, a = run(tmp_path, pl.ExternalManifestAnchor(d, SRC), fixtures=fx)
    assert m == {} and a["entries"][0]["disposition"] == "EXCLUDED"
