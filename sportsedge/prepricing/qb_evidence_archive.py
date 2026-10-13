"""Offline Form 2 archive reader. No collector or RUN IT wiring.

The manifest digest must come from independently trusted configuration, never
from the board, bundle, or adjacent editable manifest. Hash verification proves
agreement with that external pin, not publisher authenticity or clock truth.
The trusted capture writer/anchor and deployment approval remain prerequisites.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import re
from datetime import datetime, timezone

from .qb_identity_evidence import evaluate_form2_bundle

SCHEMA = "CFB_FORM2_ARCHIVE_MANIFEST_V1"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024


class EvidenceArchiveError(ValueError):
    pass


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EvidenceArchiveError("ARCHIVE_DIGEST_INVALID")
    return value


def _time(value):
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise EvidenceArchiveError("ARCHIVE_TIME_INVALID") from None


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceArchiveError("ARCHIVE_DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    def reject_constant(value):
        raise EvidenceArchiveError("ARCHIVE_NONFINITE_JSON_NUMBER")
    try:
        result = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_constant)
        pending = [(result, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 64:
                raise EvidenceArchiveError("ARCHIVE_JSON_TOO_DEEP")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return result
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, EvidenceArchiveError):
            raise
        raise EvidenceArchiveError("ARCHIVE_JSON_INVALID") from exc


def _read_bundle(root, digest):
    """Read bounded bytes from one regular file without following symlinks.

    The archive root is operator configuration. Open the root and child using
    descriptors, so swapping the root path after opening cannot redirect reads.
    O_NONBLOCK prevents a malicious FIFO from hanging before fstat can refuse it.
    """
    directory = None
    fd = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(digest + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise EvidenceArchiveError("ARCHIVE_BUNDLE_NOT_REGULAR")
        if info.st_size > MAX_BUNDLE_BYTES:
            raise EvidenceArchiveError("ARCHIVE_BUNDLE_TOO_LARGE")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            raw = handle.read(MAX_BUNDLE_BYTES + 1)
        if len(raw) > MAX_BUNDLE_BYTES:
            raise EvidenceArchiveError("ARCHIVE_BUNDLE_TOO_LARGE")
        return raw
    except OSError as exc:
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_UNREADABLE") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def load_archived_form2(root, *, manifest_bytes, trusted_manifest_sha256,
                        team_id, event_id, home_team_id, away_team_id,
                        kickoff, previous_game_kickoff, as_of):
    """Read a single content-addressed bundle with externally pinned provenance.

    Fixture identity and previous-game time must be independently verified by
    the caller. No digest, fixture, or timestamp is inferred from input lines.
    Receipt recorded_at is the archive's own completion time; it must be at
    least both fetch completion times and at most as_of, strictly pre-kickoff.
    Returns identity evidence only, with all actionable authority false.
    """
    if not isinstance(manifest_bytes, bytes):
        raise EvidenceArchiveError("ARCHIVE_MANIFEST_BYTES_REQUIRED")
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise EvidenceArchiveError("ARCHIVE_MANIFEST_TOO_LARGE")
    if hashlib.sha256(manifest_bytes).hexdigest() != _digest(trusted_manifest_sha256):
        raise EvidenceArchiveError("ARCHIVE_MANIFEST_HASH_MISMATCH")
    manifest = _json(manifest_bytes)
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise EvidenceArchiveError("ARCHIVE_SCHEMA_INVALID")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
        raise EvidenceArchiveError("ARCHIVE_ENTRIES_INVALID")
    if any(v is None or not str(v).strip() for v in (team_id, event_id, home_team_id, away_team_id)):
        raise EvidenceArchiveError("ARCHIVE_FIXTURE_REQUIRED")
    cutoff, start = _time(as_of), _time(kickoff)
    _time(previous_game_kickoff)
    if cutoff >= start:
        raise EvidenceArchiveError("ARCHIVE_NOT_PREGAME")
    matches = [e for e in entries if str(e.get("team_id")) == str(team_id)
               and str(e.get("event_id")) == str(event_id)]
    # One immutable receipt per requested fixture/team; never choose arbitrarily
    # among conflicting or repeated entries, including future revisions.
    if len(matches) != 1:
        raise EvidenceArchiveError("ARCHIVE_RECEIPT_NOT_UNIQUE")
    entry = matches[0]
    for name, expected in (("home_team_id", home_team_id), ("away_team_id", away_team_id)):
        if str(entry.get(name)) != str(expected):
            raise EvidenceArchiveError("ARCHIVE_FIXTURE_MISMATCH")
    if _time(entry.get("kickoff_utc")) != start:
        raise EvidenceArchiveError("ARCHIVE_FIXTURE_MISMATCH")
    recorded = _time(entry.get("recorded_at_utc"))
    if recorded > cutoff or recorded >= start:
        raise EvidenceArchiveError("ARCHIVE_RECEIPT_NOT_AVAILABLE")
    digest = _digest(entry.get("bundle_sha256"))
    # Content addressing avoids accepting paths supplied by the evidence itself.
    raw = _read_bundle(root, digest)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_HASH_MISMATCH")
    bundle = _json(raw)
    try:
        for key in ("depth_snapshot", "roster_snapshot"):
            if _time(bundle[key]["captured_at_utc"]) > recorded:
                raise EvidenceArchiveError("ARCHIVE_RECEIPT_PRECEDES_FETCH")
        result = evaluate_form2_bundle(
            bundle, team_id=team_id, event_id=event_id,
            home_team_id=home_team_id, away_team_id=away_team_id,
            kickoff=start, previous_game_kickoff=_time(previous_game_kickoff), now=cutoff)
    except (KeyError, TypeError, AttributeError) as exc:
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_SCHEMA_INVALID") from exc
    if not result.get("ok"):
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_REJECTED:" + str(result.get("status")))
    return {"bundle": bundle, "identity_evidence": result,
            "manifest_sha256": trusted_manifest_sha256, "bundle_sha256": digest,
            "recorded_at_utc": recorded.isoformat(),
            "research_only": True, "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}


def _publish_once(root, name, raw):
    """Publish complete bytes atomically without replacing an existing object."""
    import uuid
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temporary = ".pending-" + uuid.uuid4().hex
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
        except FileExistsError:
            # A prior publication is immutable, even when its filename looks
            # content-addressed. Verify its actual bytes before calling it reused.
            digest = name.removesuffix(".json")
            if _read_bundle(root, digest) != raw:
                raise EvidenceArchiveError("ARCHIVE_EXISTING_OBJECT_MISMATCH")
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def preserve_form2_bundle(root, *, bundle_bytes, team_id, event_id,
                          home_team_id, away_team_id, kickoff,
                          previous_game_kickoff, clock=None):
    """Offline write-once preservation, not a trusted capture or activation.

    The caller owns an existing operator-controlled directory. Source receipt
    timestamps must already exist: this function does not fetch, reconstruct,
    or certify them. The archive clock is sampled after durable bundle storage.
    The returned candidate digest is NOT an independently trusted anchor.
    A failed validation may leave a bundle object, but publishes no manifest.
    Each manifest is an immutable single-receipt snapshot, not a mutable index.
    """
    if not isinstance(bundle_bytes, bytes):
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_BYTES_REQUIRED")
    if len(bundle_bytes) > MAX_BUNDLE_BYTES:
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_TOO_LARGE")
    _json(bundle_bytes)
    digest = hashlib.sha256(bundle_bytes).hexdigest()
    _publish_once(root, digest + ".json", bundle_bytes)
    recorded = _time((clock or (lambda: datetime.now(timezone.utc)))())
    manifest = {"schema": SCHEMA, "entries": [{
        "team_id": str(team_id), "event_id": str(event_id),
        "home_team_id": str(home_team_id), "away_team_id": str(away_team_id),
        "kickoff_utc": _time(kickoff).isoformat(),
        "recorded_at_utc": recorded.isoformat(), "bundle_sha256": digest,
    }]}
    raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    candidate = hashlib.sha256(raw).hexdigest()
    # Internal consistency check only. Passing our own digest here does not
    # turn that digest into an independently anchored historical receipt.
    load_archived_form2(
        root, manifest_bytes=raw, trusted_manifest_sha256=candidate,
        team_id=team_id, event_id=event_id, home_team_id=home_team_id,
        away_team_id=away_team_id, kickoff=kickoff,
        previous_game_kickoff=previous_game_kickoff, as_of=recorded)
    _publish_once(root, candidate + ".json", raw)
    return {"manifest_bytes": raw, "candidate_manifest_sha256": candidate,
            "bundle_sha256": digest, "recorded_at_utc": recorded.isoformat(),
            "anchor_status": "UNANCHORED", "research_only": True,
            "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}
