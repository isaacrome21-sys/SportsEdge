"""Pinned Form 2 loader (CFB) -- Grok reimplementation, 2026-10-13.

Replaces the unpinned directory loader (``qb_form2_bundle_loader``) on the
RUN IT path. One-implementation rule: every byte read, digest check, JSON
parse, fixture binding, receipt-time check and Form 2 evaluation is done by
the #2164/#2165 archive reader (``qb_evidence_archive``); this module only
adds the anchor gate and whole-intake duplicate refusal around it.

Admission requires an ``ExternalManifestAnchor`` whose ``anchor_source`` is
in ``APPROVED_ANCHOR_SOURCES``. That set is EMPTY until the owner rules on
where the external anchor lives, so today admission is impossible and the
audit says so (``ANCHOR_SOURCE_NOT_APPROVED`` / ``NO_EXTERNAL_ANCHOR``).
A bare hex string, a dict, or ``preserve_form2_bundle``'s
``candidate_manifest_sha256`` is a self-computed digest and is refused.

File access: the operator root must be an absolute, existing, non-symlink
directory with no ``..`` components; the manifest and bundles are opened
by content digest only (64 lowercase hex, so no path traversal) through the
archive reader's O_NOFOLLOW / regular-file / size-bounded reads.

Output is research-only identity evidence. No fetching, no timestamps are
created here, no activation, eligibility or staking authority.
"""
from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import PurePath

from sportsedge.prepricing import qb_evidence_archive as _arch

AUDIT_SCHEMA = "SPORTSEDGE_QB_FORM2_PINNED_LOADER_AUDIT_V1"
AUDIT_SOURCE = "QB_IDENTITY_EVIDENCE_FORM2_PINNED_LOADER"

# Owner decision pending (anchor location + capture host). Empty = no anchor
# source is trusted, so no archive admission is possible.
APPROVED_ANCHOR_SOURCES: frozenset[str] = frozenset()
SELF_COMPUTED_MARKERS = frozenset({"", "SELF_COMPUTED", "CANDIDATE", "UNANCHORED",
                                   "LOCAL", "ARCHIVE", "MANIFEST"})

NO_EXTERNAL_ANCHOR = "NO_EXTERNAL_ANCHOR"
ANCHOR_NOT_EXTERNAL = "ANCHOR_NOT_EXTERNAL_SELF_COMPUTED_OR_UNTYPED"
ANCHOR_SOURCE_NOT_APPROVED = "ANCHOR_SOURCE_NOT_APPROVED"
ROOT_UNSAFE = "ARCHIVE_ROOT_UNSAFE"
WHOLE_INTAKE_DUPLICATE = "WHOLE_INTAKE_REFUSED_DUPLICATE_ENTRY"
FIXTURE_UNVERIFIED = "FIXTURE_NOT_INDEPENDENTLY_VERIFIED"
ADMITTED = "ADMITTED_PINNED_ARCHIVE"


@dataclass(frozen=True)
class ExternalManifestAnchor:
    """A manifest digest pinned OUTSIDE the archive (operator config / anchor
    service). ``anchor_source`` names where it came from; it is what makes it
    distinguishable from a digest the archive computed over itself."""
    sha256: str
    anchor_source: str

    def __post_init__(self):
        if not isinstance(self.sha256, str) or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None:
            raise ValueError("ANCHOR_DIGEST_INVALID")
        if not isinstance(self.anchor_source, str):
            raise ValueError("ANCHOR_SOURCE_INVALID")


def _audit(status, **extra):
    base = {"schema": AUDIT_SCHEMA, "source": AUDIT_SOURCE, "status": status,
            "entries": [], "admitted_team_ids": [], "anchor_status": "UNANCHORED",
            "research_only": True, "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}
    base.update(extra)
    return base


def check_anchor(anchor):
    """Return None when admissible, else the refusal reason."""
    if anchor is None:
        return NO_EXTERNAL_ANCHOR
    if type(anchor) is not ExternalManifestAnchor:
        return ANCHOR_NOT_EXTERNAL
    if anchor.anchor_source.strip().upper() in SELF_COMPUTED_MARKERS:
        return ANCHOR_NOT_EXTERNAL
    if anchor.anchor_source not in APPROVED_ANCHOR_SOURCES:
        return ANCHOR_SOURCE_NOT_APPROVED
    return None


def _safe_root(root):
    if root is None:
        return None
    try:
        text = os.fspath(root)
    except TypeError:
        return None
    if not isinstance(text, str) or "\x00" in text:
        return None
    path = PurePath(text)
    if not path.is_absolute() or ".." in path.parts:
        return None
    try:
        info = os.lstat(text)
    except (OSError, ValueError):
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        return None
    return text


def load_form2_bundles_pinned(archive_root, *, anchor, verified_fixtures, as_of):
    """Admit Form 2 bundles from a pinned archive manifest.

    ``verified_fixtures`` maps ESPN team_id -> {event_id, home_team_id,
    away_team_id, kickoff, previous_game_kickoff}, produced by the caller's
    independent fixture verification (never by the archive). Returns
    (mapping team_id -> bundle, audit). Any failure is an audited refusal.
    """
    reason = check_anchor(anchor)
    if reason is not None:
        detail = ("owner has not approved an external anchor source; archive "
                  "admission is impossible by design" if reason in
                  (NO_EXTERNAL_ANCHOR, ANCHOR_SOURCE_NOT_APPROVED) else
                  "only an ExternalManifestAnchor from an approved source is accepted")
        return {}, _audit(reason, detail=detail)
    root = _safe_root(archive_root)
    if root is None:
        return {}, _audit(ROOT_UNSAFE, anchor_status="ANCHORED")
    try:
        raw = _arch._read_bundle(root, anchor.sha256)
        if len(raw) > _arch.MAX_MANIFEST_BYTES:
            raise _arch.EvidenceArchiveError("ARCHIVE_MANIFEST_TOO_LARGE")
        import hashlib
        if hashlib.sha256(raw).hexdigest() != anchor.sha256:
            raise _arch.EvidenceArchiveError("ARCHIVE_MANIFEST_HASH_MISMATCH")
        manifest = _arch._json(raw)
    except _arch.EvidenceArchiveError as exc:
        return {}, _audit(str(exc), anchor_status="ANCHORED")
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    if (not isinstance(manifest, dict) or manifest.get("schema") != _arch.SCHEMA
            or not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries)):
        return {}, _audit("ARCHIVE_SCHEMA_INVALID", anchor_status="ANCHORED")
    teams = [str(e.get("team_id")) for e in entries]
    digests = [str(e.get("bundle_sha256")) for e in entries]
    if len(set(teams)) != len(teams) or len(set(digests)) != len(digests):
        return {}, _audit(WHOLE_INTAKE_DUPLICATE, anchor_status="ANCHORED",
                          detail="duplicate team or bundle entry; entire intake refused")
    mapping, audit = {}, _audit("LOADED", anchor_status="ANCHORED")
    fixtures = verified_fixtures if isinstance(verified_fixtures, dict) else {}
    for team_id in teams:
        fx = fixtures.get(team_id)
        if not isinstance(fx, dict):
            audit["entries"].append({"team_id": team_id, "disposition": "EXCLUDED",
                                     "reason": FIXTURE_UNVERIFIED})
            continue
        try:
            result = _arch.load_archived_form2(
                root, manifest_bytes=raw, trusted_manifest_sha256=anchor.sha256,
                team_id=team_id, event_id=fx.get("event_id"),
                home_team_id=fx.get("home_team_id"), away_team_id=fx.get("away_team_id"),
                kickoff=fx.get("kickoff"), previous_game_kickoff=fx.get("previous_game_kickoff"),
                as_of=as_of)
        except _arch.EvidenceArchiveError as exc:
            audit["entries"].append({"team_id": team_id, "disposition": "EXCLUDED",
                                     "reason": str(exc)})
            continue
        except Exception as exc:  # fail closed on any unexpected input shape
            audit["entries"].append({"team_id": team_id, "disposition": "EXCLUDED",
                                     "reason": "UNEXPECTED_" + type(exc).__name__})
            continue
        mapping[team_id] = result["bundle"]
        audit["entries"].append({"team_id": team_id, "disposition": "ADMITTED",
                                 "reason": ADMITTED,
                                 "bundle_sha256": result["bundle_sha256"]})
    audit["admitted_team_ids"] = sorted(mapping)
    return mapping, audit
