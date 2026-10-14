"""Adversarial tests: #2164/#2165 archive hardening (Grok, 2026-10-13).

Closes review comment 6155378890: trusted writer clock, 2000/2099 sentinel
dates, anchor-enforced admission, and bundle+manifest pair intent.
"""
import hashlib
import inspect
import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge.prepricing import qb_evidence_archive as arch
from sportsedge.prepricing import qb_form2_pinned_loader as pl
from tests.test_cfb_qb_evidence_archive import (
    setup_archive, load, preserve, TEST_ANCHOR_SOURCE, _approved_test_anchor,  # noqa: F401 (autouse)
)
from tests.test_cfb_qb_identity_evidence_form2_20261013 import NOW, KICKOFF, CHARTS


def pin(manifest):
    return hashlib.sha256(json.dumps(manifest).encode()).hexdigest()


# ---- 1. writer clock is the trusted system clock --------------------------

def test_writer_has_no_caller_clock_parameter():
    params = inspect.signature(arch.preserve_form2_bundle).parameters
    assert "clock" not in params and not any(
        p.kind is p.VAR_KEYWORD for p in params.values())


def test_writer_refuses_caller_supplied_clock(tmp_path):
    with pytest.raises(TypeError):
        preserve(tmp_path, clock=lambda: NOW)
    assert not [p for p in tmp_path.iterdir() if not p.name.startswith(".pair")]


def test_writer_recorded_time_comes_from_time_ns(tmp_path):
    when = NOW - timedelta(minutes=7)
    out = preserve(tmp_path, when=when)
    assert datetime.fromisoformat(out["recorded_at_utc"]) == when


def test_writer_with_real_clock_after_kickoff_never_publishes(tmp_path):
    # The real clock (now) is past the fixture kickoff: must fail closed.
    import time
    real = time.time_ns
    with pytest.raises(arch.EvidenceArchiveError, match="NOT_PREGAME"):
        preserve(tmp_path, when=real)
    assert not list(tmp_path.glob("*.json"))[1:]  # at most the orphan bundle


@pytest.mark.parametrize("bad", [datetime(2000, 1, 1, tzinfo=timezone.utc),
                                 datetime(1970, 1, 1, tzinfo=timezone.utc)])
def test_writer_refuses_rolled_back_system_clock(tmp_path, bad):
    with pytest.raises(arch.EvidenceArchiveError, match="BEFORE_FLOOR"):
        preserve(tmp_path, when=bad)
    assert not list(tmp_path.glob("*.json"))[1:]


# ---- 2. sentinel / future dates -------------------------------------------

@pytest.mark.parametrize("field,value,code", [
    ("recorded_at_utc", "2000-01-01T00:00:00Z", "BEFORE_FLOOR"),
    ("recorded_at_utc", "2019-12-31T23:59:59Z", "BEFORE_FLOOR"),
    ("recorded_at_utc", "2099-01-01T00:00:00Z", "IN_FUTURE"),
    ("kickoff_utc", "2000-01-01T00:00:00Z", "BEFORE_FLOOR"),
])
def test_manifest_sentinel_dates_rejected(tmp_path, field, value, code):
    manifest, _ = setup_archive(tmp_path, mutate_entry=lambda e: e.update({field: value}))
    with pytest.raises(arch.EvidenceArchiveError, match=code):
        load(tmp_path, manifest)


@pytest.mark.parametrize("value", ["2000-01-01T00:00:00Z", "2099-06-01T00:00:00Z"])
def test_bundle_fetch_sentinel_dates_rejected(tmp_path, value):
    def mut(b):
        b["depth_snapshot"]["captured_at_utc"] = value
    manifest, _ = setup_archive(tmp_path, mutate_bundle=mut)
    with pytest.raises(arch.EvidenceArchiveError, match="BEFORE_FLOOR|IN_FUTURE"):
        load(tmp_path, manifest)


def test_as_of_in_future_beyond_skew_rejected(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    future = datetime.now(timezone.utc) + timedelta(seconds=60)
    with pytest.raises(arch.EvidenceArchiveError, match="IN_FUTURE"):
        load(tmp_path, manifest, as_of=future, kickoff=future + timedelta(hours=1))


def test_future_skew_boundary(monkeypatch):
    import time
    base = datetime(2026, 10, 13, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(time, "time_ns", lambda: int(base.timestamp() * 1e9))
    assert arch._time(base + timedelta(seconds=5), past=True)
    with pytest.raises(arch.EvidenceArchiveError, match="IN_FUTURE"):
        arch._time(base + timedelta(seconds=6), past=True)
    assert arch._time(datetime(2020, 1, 1, tzinfo=timezone.utc))
    with pytest.raises(arch.EvidenceArchiveError, match="BEFORE_FLOOR"):
        arch._time(datetime(2019, 12, 31, 23, 59, 59, tzinfo=timezone.utc))


@pytest.mark.parametrize("value", [True, 0, 1.5, None, "", "garbage", [], {},
                                   "9999-12-31T23:59:59+00:00", "2026-10-13T12:00:00"])
def test_wrong_type_times_fail_named(value):
    with pytest.raises(arch.EvidenceArchiveError, match="ARCHIVE_TIME_"):
        arch._time(value, past=True)


# ---- 3. admission requires an approved external anchor ---------------------

def test_admission_impossible_with_default_empty_approved_set(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset())
    manifest, _ = setup_archive(tmp_path)
    with pytest.raises(arch.EvidenceArchiveError, match="ANCHOR_REFUSED:ANCHOR_SOURCE_NOT_APPROVED"):
        load(tmp_path, manifest)


@pytest.mark.parametrize("anchor", [None, "BARE", {"sha256": "x", "anchor_source": TEST_ANCHOR_SOURCE}])
def test_bare_or_untyped_anchor_refused(tmp_path, anchor):
    manifest, _ = setup_archive(tmp_path)
    a = pin(manifest) if anchor == "BARE" else anchor
    with pytest.raises(arch.EvidenceArchiveError, match="ANCHOR_REFUSED"):
        load(tmp_path, manifest, anchor=a)


@pytest.mark.parametrize("src", ["UNANCHORED", "SELF_COMPUTED", "candidate", ""])
def test_self_computed_anchor_labels_refused_even_if_approved(tmp_path, monkeypatch, src):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset({src}))
    manifest, _ = setup_archive(tmp_path)
    with pytest.raises(arch.EvidenceArchiveError, match="ANCHOR_NOT_EXTERNAL"):
        load(tmp_path, manifest, anchor=pl.ExternalManifestAnchor(pin(manifest), src))


def test_anchor_must_pin_the_supplied_manifest(tmp_path):
    manifest, _ = setup_archive(tmp_path)
    other = pl.ExternalManifestAnchor("0" * 64, TEST_ANCHOR_SOURCE)
    with pytest.raises(arch.EvidenceArchiveError, match="ANCHOR_MISMATCH"):
        load(tmp_path, manifest, anchor=other)


def test_writer_candidate_digest_cannot_self_admit(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset())
    out = preserve(tmp_path)
    assert out["anchor_status"] == "UNANCHORED"
    with pytest.raises(arch.EvidenceArchiveError, match="ANCHOR_REFUSED"):
        load(tmp_path, json.loads(out["manifest_bytes"]),
             trusted_manifest_sha256=out["candidate_manifest_sha256"],
             anchor=out["candidate_manifest_sha256"])


def test_public_loader_requires_anchor_keyword():
    assert inspect.signature(arch.load_archived_form2).parameters["anchor"].default \
        is inspect.Parameter.empty


# ---- 4. bundle+manifest pair intent ---------------------------------------

def test_success_clears_pair_intent(tmp_path):
    preserve(tmp_path)
    assert arch.incomplete_pair_intents(tmp_path) == []


def test_crash_between_bundle_and_manifest_is_detected(tmp_path, monkeypatch):
    real = arch._publish_once
    def crash_on_manifest(root, name, raw):
        if b'"entries"' in raw and b"CFB_FORM2_ARCHIVE_MANIFEST_V1" in raw:
            raise SystemExit("simulated crash before manifest")
        return real(root, name, raw)
    monkeypatch.setattr(arch, "_publish_once", crash_on_manifest)
    with pytest.raises(SystemExit):
        preserve(tmp_path)
    leftovers = arch.incomplete_pair_intents(tmp_path)
    assert len(leftovers) == 1
    body = json.loads((tmp_path / leftovers[0]).read_bytes())
    assert body["schema"] == "CFB_FORM2_ARCHIVE_PAIR_INTENT_V1"
    assert (tmp_path / (body["bundle_sha256"] + ".json")).exists()


def test_crash_before_intent_clear_blocks_admission(tmp_path, monkeypatch):
    monkeypatch.setattr(arch, "_clear_pair_intent", lambda root, name: None)
    out = preserve(tmp_path)
    assert arch.incomplete_pair_intents(tmp_path, bundle_sha256=out["bundle_sha256"])
    with pytest.raises(arch.EvidenceArchiveError, match="PAIR_INCOMPLETE"):
        load(tmp_path, json.loads(out["manifest_bytes"]))


def test_hand_planted_intent_blocks_matching_bundle_only(tmp_path):
    manifest, digest = setup_archive(tmp_path)
    (tmp_path / (arch.PAIR_INTENT_PREFIX + digest + "-deadbeef")).write_bytes(b"{}")
    with pytest.raises(arch.EvidenceArchiveError, match="PAIR_INCOMPLETE"):
        load(tmp_path, manifest)
    (tmp_path / (arch.PAIR_INTENT_PREFIX + digest + "-deadbeef")).unlink()
    (tmp_path / (arch.PAIR_INTENT_PREFIX + "f" * 64 + "-x")).write_bytes(b"{}")
    assert load(tmp_path, manifest)["identity_evidence"]["ok"]


def test_intent_fsync_failure_leaves_nothing(tmp_path, monkeypatch):
    def fail(fd):
        raise OSError("disk")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError):
        preserve(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unlistable_root_counts_as_incomplete(tmp_path):
    assert arch.incomplete_pair_intents(tmp_path / "missing") == ["<ROOT_UNLISTABLE>"]


def test_pinned_loader_excludes_entry_with_incomplete_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "APPROVED_ANCHOR_SOURCES", frozenset({TEST_ANCHOR_SOURCE}))
    manifest, digest = setup_archive(tmp_path)
    raw = json.dumps(manifest).encode()
    d = hashlib.sha256(raw).hexdigest()
    (tmp_path / (d + ".json")).write_bytes(raw)
    (tmp_path / (arch.PAIR_INTENT_PREFIX + digest + "-x")).write_bytes(b"{}")
    fx = {"48": dict(event_id="401871067", home_team_id="2393", away_team_id="48",
                     kickoff=KICKOFF, previous_game_kickoff=CHARTS["48"][3])}
    m, a = pl.load_form2_bundles_pinned(str(tmp_path), anchor=pl.ExternalManifestAnchor(d, TEST_ANCHOR_SOURCE),
                                        verified_fixtures=fx, as_of=NOW)
    assert m == {} and a["entries"][0]["reason"] == "ARCHIVE_PAIR_INCOMPLETE"
