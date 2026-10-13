"""Offline Form 2 archive reader. No collector or RUN IT wiring.

The manifest digest must come from independently trusted configuration, never
from the board, bundle, or adjacent editable manifest. Hash verification proves
agreement with that external pin, not publisher authenticity or clock truth.
The trusted capture writer/anchor and deployment approval remain prerequisites.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .qb_identity_evidence import evaluate_form2_bundle

SCHEMA = "CFB_FORM2_ARCHIVE_MANIFEST_V1"


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
    try:
        return json.loads(raw, object_pairs_hook=unique)
    except (UnicodeError, ValueError) as exc:
        if isinstance(exc, EvidenceArchiveError):
            raise
        raise EvidenceArchiveError("ARCHIVE_JSON_INVALID") from exc


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
    path = Path(root) / (digest + ".json")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_UNREADABLE") from exc
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
