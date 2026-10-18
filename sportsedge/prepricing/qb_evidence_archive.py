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
import time
import uuid
from datetime import datetime, timedelta, timezone

from .qb_identity_evidence import evaluate_form2_bundle

SCHEMA = "CFB_FORM2_ARCHIVE_MANIFEST_V1"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
# Hardening 2026-10-13 (Grok): sentinel/default dates (2000-01-01, 2099-...)
# are refused. Any evidence time must be >= TIME_FLOOR; times that claim to
# have already happened (receipts, fetches, as_of) may not exceed the trusted
# system clock by more than FUTURE_SKEW.
TIME_FLOOR = datetime(2020, 1, 1, tzinfo=timezone.utc)
FUTURE_SKEW = timedelta(seconds=5)
PAIR_INTENT_PREFIX = ".pair-intent-"


class EvidenceArchiveError(ValueError):
    pass


def _digest(value):
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise EvidenceArchiveError("ARCHIVE_DIGEST_INVALID")
    return value


def _system_now():
    """Trusted system clock. Never caller-supplied."""
    return datetime.fromtimestamp(time.time_ns() / 1e9, tz=timezone.utc)


def _time(value, *, past=False):
    try:
        if isinstance(value, bool):
            raise TypeError()
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError()
        parsed = parsed.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise EvidenceArchiveError("ARCHIVE_TIME_INVALID") from None
    if parsed < TIME_FLOOR:
        raise EvidenceArchiveError("ARCHIVE_TIME_BEFORE_FLOOR")
    if past and parsed > _system_now() + FUTURE_SKEW:
        raise EvidenceArchiveError("ARCHIVE_TIME_IN_FUTURE")
    return parsed


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


def load_archived_form2(root, *, anchor, manifest_bytes, trusted_manifest_sha256,
                        team_id, event_id, home_team_id, away_team_id,
                        kickoff, previous_game_kickoff, as_of):
    """Archive-backed admission. Requires an approved external anchor.

    The anchor check is the pinned loader's ``check_anchor`` (one
    implementation). A bare digest -- including ``preserve_form2_bundle``'s
    own candidate -- is refused, and the anchor must pin exactly the manifest
    supplied. With no approved source (today) admission is impossible.
    """
    from .qb_form2_pinned_loader import check_anchor
    reason = check_anchor(anchor)
    if reason is not None:
        raise EvidenceArchiveError("ARCHIVE_ANCHOR_REFUSED:" + reason)
    if _digest(trusted_manifest_sha256) != anchor.sha256:
        raise EvidenceArchiveError("ARCHIVE_ANCHOR_MISMATCH")
    return _verify_archived_form2(
        root, manifest_bytes=manifest_bytes, trusted_manifest_sha256=trusted_manifest_sha256,
        team_id=team_id, event_id=event_id, home_team_id=home_team_id,
        away_team_id=away_team_id, kickoff=kickoff,
        previous_game_kickoff=previous_game_kickoff, as_of=as_of)


def _verify_archived_form2(root, *, manifest_bytes, trusted_manifest_sha256,
                           team_id, event_id, home_team_id, away_team_id,
                           kickoff, previous_game_kickoff, as_of, _own_intent=None):
    """Internal verification (no admission authority). Read a single content-addressed bundle with externally pinned provenance.

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
    cutoff, start = _time(as_of, past=True), _time(kickoff)
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
    recorded = _time(entry.get("recorded_at_utc"), past=True)
    if recorded > cutoff or recorded >= start:
        raise EvidenceArchiveError("ARCHIVE_RECEIPT_NOT_AVAILABLE")
    digest = _digest(entry.get("bundle_sha256"))
    if [n for n in incomplete_pair_intents(root, bundle_sha256=digest) if n != _own_intent]:
        raise EvidenceArchiveError("ARCHIVE_PAIR_INCOMPLETE")
    # Content addressing avoids accepting paths supplied by the evidence itself.
    raw = _read_bundle(root, digest)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise EvidenceArchiveError("ARCHIVE_BUNDLE_HASH_MISMATCH")
    bundle = _json(raw)
    try:
        for key in ("depth_snapshot", "roster_snapshot"):
            if _time(bundle[key]["captured_at_utc"], past=True) > recorded:
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


def _fsync_dir(root):
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _write_pair_intent(root, bundle_sha256):
    """Durably record intent to publish a bundle+manifest pair BEFORE either
    write. Removed only after the manifest is durable, so a crash anywhere in
    between leaves the intent behind and the pair is detected as incomplete."""
    name = PAIR_INTENT_PREFIX + bundle_sha256 + "-" + uuid.uuid4().hex
    body = json.dumps({"schema": "CFB_FORM2_ARCHIVE_PAIR_INTENT_V1",
                       "bundle_sha256": bundle_sha256,
                       "started_ns": time.time_ns()}, sort_keys=True).encode()
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.fsync(directory)
        except BaseException:
            # Nothing of the pair has been written yet; an undurable intent
            # is withdrawn rather than left as a false crash signal.
            try:
                os.unlink(name, dir_fd=directory)
            except OSError:
                pass
            raise
    finally:
        os.close(directory)
    return name


def _clear_pair_intent(root, name):
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.unlink(name, dir_fd=directory)
        os.fsync(directory)
    finally:
        os.close(directory)


def incomplete_pair_intents(root, *, bundle_sha256=None):
    """Names of leftover pair intents (crash between bundle and manifest
    writes, or a writer still running). Unreadable root -> treated as
    incomplete so callers fail closed."""
    try:
        names = os.listdir(root)
    except (OSError, TypeError, ValueError):
        return ["<ROOT_UNLISTABLE>"]
    prefix = PAIR_INTENT_PREFIX + (bundle_sha256 + "-" if bundle_sha256 else "")
    return sorted(n for n in names if n.startswith(prefix))


def _publish_once(root, name, raw):
    """Publish complete bytes atomically without replacing an existing object."""
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
                          previous_game_kickoff):
    """Offline write-once preservation, not a trusted capture or activation.

    The caller owns an existing operator-controlled directory. Source receipt
    timestamps must already exist: this function does not fetch, reconstruct,
    or certify them. The archive time is the trusted system clock
    (time.time_ns), sampled after durable bundle storage; no caller clock.
    A shared pair intent is written before the bundle and cleared only after
    the manifest is durable, so a crash between the two is detectable.
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
    intent = _write_pair_intent(root, digest)
    _publish_once(root, digest + ".json", bundle_bytes)
    recorded = _time(_system_now(), past=True)
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
    _verify_archived_form2(
        root, manifest_bytes=raw, trusted_manifest_sha256=candidate,
        team_id=team_id, event_id=event_id, home_team_id=home_team_id,
        away_team_id=away_team_id, kickoff=kickoff,
        previous_game_kickoff=previous_game_kickoff, as_of=recorded, _own_intent=intent)
    _publish_once(root, candidate + ".json", raw)
    _clear_pair_intent(root, intent)
    return {"manifest_bytes": raw, "candidate_manifest_sha256": candidate,
            "bundle_sha256": digest, "recorded_at_utc": recorded.isoformat(),
            "anchor_status": "UNANCHORED", "research_only": True,
            "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}


def seal_form2_archive_manifest(root, *, manifest_sha256s):
    """Seal ONE archive-level manifest over already-preserved bundles.

    preserve_form2_bundle seals each bundle under an immutable
    single-receipt manifest snapshot, by design not a mutable index.
    Operative consumers take a SINGLE external pin for a whole
    capture (the RUN IT Form 2 loader's manifest_sha256), so a
    multi-team capture also needs one manifest enumerating every
    receipt. This sealer is that enumeration step, and nothing more:
    each named single-receipt manifest object is read back from the
    store through the archive's own bounded read and its bytes are
    verified against the digest the caller names (never trusted
    from the caller); every referenced bundle object is likewise
    re-read and verified against its content address; and each
    receipt is bound to its bundle -- team, event, home/away roles,
    kickoff, and the receipt ordering (recorded no earlier than
    either snapshot's capture completion, strictly before kickoff) --
    with the same checks and refusal codes the archive readers
    enforce. The combined manifest is published as one more
    immutable content-addressed object; per-receipt manifests and
    bundles are never modified. Sealing enumerates receipts whose
    bundles already passed full evaluation at preserve time; it
    does not re-evaluate, fetch, or certify anything, and the
    returned candidate digest is NOT an independently trusted
    anchor -- it becomes a consumer's pin only when an operator
    supplies it from an independent channel. A receipt set that
    covers one fixture/team twice fails closed, exactly as at read
    time, and a failed seal publishes nothing. Re-sealing the same
    receipt set is idempotent (identical bytes, reused object).
    """
    if isinstance(manifest_sha256s, (str, bytes)) \
            or not manifest_sha256s:
        raise EvidenceArchiveError("ARCHIVE_SEAL_NO_MANIFESTS")
    entries = []
    seen_fixtures = set()
    seen_bundles = set()
    for value in manifest_sha256s:
        pin = _digest(value)
        raw_manifest = _read_bundle(root, pin)
        if len(raw_manifest) > MAX_MANIFEST_BYTES:
            raise EvidenceArchiveError("ARCHIVE_MANIFEST_TOO_LARGE")
        if hashlib.sha256(raw_manifest).hexdigest() != pin:
            raise EvidenceArchiveError("ARCHIVE_MANIFEST_HASH_MISMATCH")
        manifest = _json(raw_manifest)
        if not isinstance(manifest, dict) \
                or manifest.get("schema") != SCHEMA:
            raise EvidenceArchiveError("ARCHIVE_SCHEMA_INVALID")
        receipts = manifest.get("entries")
        if not isinstance(receipts, list) \
                or any(not isinstance(e, dict) for e in receipts):
            raise EvidenceArchiveError("ARCHIVE_ENTRIES_INVALID")
        if len(receipts) != 1:
            raise EvidenceArchiveError(
                "ARCHIVE_SEAL_REQUIRES_SINGLE_RECEIPT_MANIFEST")
        entry = receipts[0]
        if any(entry.get(name) is None or not str(entry.get(name)).strip()
               for name in ("team_id", "event_id", "home_team_id",
                            "away_team_id", "kickoff_utc",
                            "recorded_at_utc", "bundle_sha256")):
            raise EvidenceArchiveError("ARCHIVE_ENTRIES_INVALID")
        fixture_key = (str(entry["team_id"]), str(entry["event_id"]))
        if fixture_key in seen_fixtures:
            raise EvidenceArchiveError("ARCHIVE_RECEIPT_NOT_UNIQUE")
        seen_fixtures.add(fixture_key)
        digest = _digest(entry["bundle_sha256"])
        if digest in seen_bundles:
            raise EvidenceArchiveError("ARCHIVE_RECEIPT_NOT_UNIQUE")
        seen_bundles.add(digest)
        raw_bundle = _read_bundle(root, digest)
        if hashlib.sha256(raw_bundle).hexdigest() != digest:
            raise EvidenceArchiveError("ARCHIVE_BUNDLE_HASH_MISMATCH")
        bundle = _json(raw_bundle)
        if not isinstance(bundle, dict) \
                or bundle.get("schema") == SCHEMA:
            raise EvidenceArchiveError("ARCHIVE_BUNDLE_SCHEMA_INVALID")
        try:
            team = bundle["team"]
            fixture = bundle["fixture"]
            if str(entry["team_id"]) != str(team["espn_id"]):
                raise EvidenceArchiveError("ARCHIVE_FIXTURE_MISMATCH")
            if str(entry["event_id"]) != str(fixture["event_id"]):
                raise EvidenceArchiveError("ARCHIVE_FIXTURE_MISMATCH")
            roles = {str(entry["home_team_id"]), str(entry["away_team_id"])}
            if roles != {str(team["espn_id"]),
                         str(fixture["opponent_espn_id"])}:
                raise EvidenceArchiveError("ARCHIVE_FIXTURE_MISMATCH")
            kickoff = _time(entry["kickoff_utc"])
            if kickoff != _time(fixture["kickoff_utc"]):
                raise EvidenceArchiveError("ARCHIVE_FIXTURE_MISMATCH")
            recorded = _time(entry["recorded_at_utc"])
            captured = [_time(bundle["depth_snapshot"]["captured_at_utc"]),
                        _time(bundle["roster_snapshot"]["captured_at_utc"])]
        except (KeyError, TypeError, AttributeError) as exc:
            raise EvidenceArchiveError(
                "ARCHIVE_BUNDLE_SCHEMA_INVALID") from exc
        if any(recorded < stamp for stamp in captured):
            raise EvidenceArchiveError("ARCHIVE_RECEIPT_PRECEDES_FETCH")
        if recorded >= kickoff:
            raise EvidenceArchiveError("ARCHIVE_RECEIPT_NOT_AVAILABLE")
        entries.append(entry)
    entries.sort(key=lambda e: (str(e["event_id"]), str(e["team_id"]),
                                str(e["bundle_sha256"])))
    combined = {"schema": SCHEMA, "entries": entries}
    raw = json.dumps(combined, sort_keys=True,
                     separators=(",", ":")).encode()
    if len(raw) > MAX_MANIFEST_BYTES:
        raise EvidenceArchiveError("ARCHIVE_MANIFEST_TOO_LARGE")
    candidate = hashlib.sha256(raw).hexdigest()
    _publish_once(root, candidate + ".json", raw)
    return {"manifest_bytes": raw, "candidate_manifest_sha256": candidate,
            "bundle_sha256s": sorted(seen_bundles),
            "receipt_count": len(entries),
            "anchor_status": "UNANCHORED", "research_only": True,
            "eligibility": False, "staking_allowed": False,
            "activation_allowed": False}
