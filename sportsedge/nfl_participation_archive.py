"""Anchored loader for NFL participation evidence bundles.

Trust contract (mirrors the Form 2 archive discipline in
``sportsedge.prepricing.qb_evidence_archive`` /
``qb_form2_bundle_loader``; applied to PR #2274 audit item B2):

  * A participation bundle carried inline in the RUN IT odds payload is
    UNTRUSTED caller input.  It may be displayed as research context,
    but it can never lift the phone pricer's
    ``STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG`` stamp.  Only a bundle
    loaded through THIS module -- from an operator-configured archive
    root, against an EXTERNAL PIN supplied from an independent channel
    (runner configuration, never the payload, never the archive root
    itself) -- carries verified provenance.
  * The archive root holds ``manifest.json`` plus one content-addressed
    bundle object ``<bundle_sha256>.json``.  The manifest bytes must
    hash to the external pin before anything is parsed for admission;
    the bundle object's raw bytes must hash to the content address the
    pinned manifest carries for it.  A manifest's own self-consistency
    proves nothing without the pin (a resealed forgery recomputes its
    own hashes), so there is NO unpinned acceptance path: no pin, no
    root, no admission -- the caller records ``UNVERIFIED_BUNDLE`` and
    the conservative stamp stays.
  * All file IO here is descriptor-based, size-capped, and refuses
    symlinks/FIFOs (the Form 2 archive read discipline); JSON parsing
    is strict (duplicate keys, nonfinite numbers, and excess nesting
    are refusals, not silent reinterpretations).
  * The manifest is a single-receipt snapshot: exactly one entry.
    ``recorded_at_utc`` is the archive's own completion time and must
    be at or before the caller's as-of clock (the as-of binding).

This module performs NO fetching of any kind.  Capture and
preservation are operator-invoked ahead of kickoff; a writer is
deliberately out of scope here (the receipt track that produces
trusted captures remains on HOLD).  Loading proves the bytes agree
with the external pin -- not publisher authenticity or clock truth --
exactly the Form 2 archive's stated limit.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = "SPORTSEDGE_NFL_PARTICIPATION_MANIFEST_V1"
BUNDLE_SCHEMA = "SPORTSEDGE_NFL_PARTICIPATION_BUNDLE_V1"
# Versioned ESPN-athlete-ID <-> GSIS-ID crosswalk contract (audit B3):
# a bundle whose bindings do not declare this version is not a checked
# crosswalk and cannot support a stamp lift.
CROSSWALK_VERSION = "ESPN_GSIS_CROSSWALK_V1"

MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024

_BUNDLE_LIST_KEYS = (
    "depth_rows", "injury_rows", "inactive_rows", "inactive_snapshots",
    "games", "player_bindings",
)


class ArchiveProvenance:
    """Non-JSON provenance token attached ONLY by
    :func:`load_participation_bundle` to inactive snapshots it loaded
    against an external pin.  A dict field such as ``complete: True`` or
    any JSON value can never equal an instance of this class, so caller
    payloads cannot forge it (#2274 completeness-proof ruling, t207u).
    """

    __slots__ = ("manifest_sha256", "bundle_sha256")

    def __init__(self, manifest_sha256: str, bundle_sha256: str) -> None:
        self.manifest_sha256 = manifest_sha256
        self.bundle_sha256 = bundle_sha256


PROVENANCE_KEY = "_archive_provenance"


class ParticipationArchiveError(ValueError):
    """Named fail-closed refusal from the participation archive loader."""


def _digest(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_DIGEST_INVALID")
    return value


def _time(value: Any) -> datetime:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
            str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_TIME_INVALID") from None


def _json_strict(raw: bytes, *, what: str) -> Any:
    """Strict JSON: duplicate keys / nonfinite / deep nesting refuse."""
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ParticipationArchiveError(
                    f"NFL_PARTICIPATION_ARCHIVE_{what}_DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def reject_constant(value):
        raise ParticipationArchiveError(
            f"NFL_PARTICIPATION_ARCHIVE_{what}_NONFINITE_JSON_NUMBER")

    try:
        result = json.loads(raw, object_pairs_hook=unique,
                            parse_constant=reject_constant)
        pending = [(result, 0)]
        while pending:
            value, depth = pending.pop()
            if depth > 64:
                raise ParticipationArchiveError(
                    f"NFL_PARTICIPATION_ARCHIVE_{what}_JSON_TOO_DEEP")
            if isinstance(value, dict):
                pending.extend((item, depth + 1) for item in value.values())
            elif isinstance(value, list):
                pending.extend((item, depth + 1) for item in value)
        return result
    except ParticipationArchiveError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ParticipationArchiveError(
            f"NFL_PARTICIPATION_ARCHIVE_{what}_JSON_INVALID") from exc


def _read_named(root: str | Path, name: str, *, max_bytes: int,
                what: str) -> bytes:
    """Bounded descriptor read of one regular file below ``root``.

    Opens the root and the child by descriptor with O_NOFOLLOW, so a
    swapped path or symlink cannot redirect the read, and O_NONBLOCK
    prevents a FIFO from hanging the run before fstat can refuse it --
    the Form 2 archive's read discipline, applied verbatim in kind.
    """
    directory = None
    fd = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                     dir_fd=directory)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ParticipationArchiveError(
                f"NFL_PARTICIPATION_ARCHIVE_{what}_NOT_REGULAR")
        if info.st_size > max_bytes:
            raise ParticipationArchiveError(
                f"NFL_PARTICIPATION_ARCHIVE_{what}_TOO_LARGE")
        with os.fdopen(fd, "rb") as handle:
            fd = None
            raw = handle.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ParticipationArchiveError(
                f"NFL_PARTICIPATION_ARCHIVE_{what}_TOO_LARGE")
        return raw
    except ParticipationArchiveError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ParticipationArchiveError(
            f"NFL_PARTICIPATION_ARCHIVE_{what}_UNREADABLE") from exc
    finally:
        if fd is not None:
            os.close(fd)
        if directory is not None:
            os.close(directory)


def load_participation_bundle(root: str | Path, *,
                              manifest_sha256: str,
                              as_of: Any) -> dict[str, Any]:
    """Load one participation bundle with externally pinned provenance.

    ``root`` is operator configuration (a local archive directory);
    ``manifest_sha256`` is the external pin from an independent
    channel.  Returns the verified bundle plus its provenance digests.
    Every failure raises :class:`ParticipationArchiveError` with a
    named code; the caller records ``UNVERIFIED_BUNDLE`` and keeps the
    conservative phone stamp.
    """
    pin = _digest(manifest_sha256)
    manifest_raw = _read_named(root, "manifest.json",
                               max_bytes=MAX_MANIFEST_BYTES, what="MANIFEST")
    if hashlib.sha256(manifest_raw).hexdigest() != pin:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_MANIFEST_HASH_MISMATCH")
    manifest = _json_strict(manifest_raw, what="MANIFEST")
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_SCHEMA_INVALID")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or any(
            not isinstance(e, dict) for e in entries):
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_ENTRIES_INVALID")
    # One immutable receipt per archive snapshot; never choose among
    # competing entries (the Form 2 archive's uniqueness rule).
    if len(entries) != 1:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_RECEIPT_NOT_UNIQUE")
    entry = entries[0]
    recorded = _time(entry.get("recorded_at_utc"))
    cutoff = _time(as_of)
    if recorded > cutoff:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_RECEIPT_NOT_AVAILABLE")
    digest = _digest(entry.get("bundle_sha256"))
    # Content addressing: the object name comes from the pinned
    # manifest's digest, never from a path the evidence supplies.
    raw = _read_named(root, digest + ".json",
                      max_bytes=MAX_BUNDLE_BYTES, what="BUNDLE")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_BUNDLE_HASH_MISMATCH")
    bundle = _json_strict(raw, what="BUNDLE")
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_BUNDLE_SCHEMA_INVALID")
    for key in _BUNDLE_LIST_KEYS:
        rows = bundle.get(key)
        if not isinstance(rows, list) or any(
                not isinstance(r, dict) for r in rows):
            raise ParticipationArchiveError(
                "NFL_PARTICIPATION_ARCHIVE_BUNDLE_SCHEMA_INVALID")
    if bundle.get("player_bindings_version") != CROSSWALK_VERSION:
        raise ParticipationArchiveError(
            "NFL_PARTICIPATION_ARCHIVE_BINDINGS_VERSION_UNSUPPORTED")
    token = ArchiveProvenance(pin, digest)
    for snap in bundle["inactive_snapshots"]:
        snap[PROVENANCE_KEY] = token
    return {
        "bundle": bundle,
        "manifest_sha256": pin,
        "bundle_sha256": digest,
        "recorded_at_utc": recorded.isoformat(),
        "research_only": True,
        "official_authority": False,
        "model_p_authority": False,
        "staking_authority": False,
    }


__all__ = [
    "ArchiveProvenance",
    "PROVENANCE_KEY",
    "BUNDLE_SCHEMA",
    "CROSSWALK_VERSION",
    "MAX_BUNDLE_BYTES",
    "MAX_MANIFEST_BYTES",
    "SCHEMA",
    "ParticipationArchiveError",
    "load_participation_bundle",
]
