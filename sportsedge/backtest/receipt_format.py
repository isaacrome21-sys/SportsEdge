"""Owner receipt format: observation vs effective-availability evidence.

The receipt-first safeguard (``capture_receipt.py``) preserves a
capture input write-once and journals its outcome. This module is
the owner's receipt format (Isaac's approval package, Oct 12 2026),
built as an **extension of — not a replacement for** — that
safeguard: an envelope that binds one immutable source payload to
the two distinct instants evidence discipline keeps separate:

- ``observed_at_utc`` — when *we* observed the payload (retrieval
  instant). This is what a consumer-read stamp can honestly claim.
- ``effective_at_utc`` — when the information in the payload
  actually **became available** at its source. A fact can be
  observed long after it became available (a roster page fetched
  Tuesday describing a Monday designation), and stamping the
  observation instant as the availability instant is the
  provenance conflation the Elo cache work kept hitting.

An envelope asserts an effective time only with a stated basis
(``effective_at_basis``) and never earlier than that basis
supports:

- ``SOURCE_TIMESTAMP`` — the source's own timestamp, carried
  inside the payload itself (``effective_at_basis_field`` names
  the payload field). The effective time must equal the value the
  payload carries: the payload is the evidence, so an effective
  time the payload does not state cannot be asserted at all, and
  one earlier than it states is fabrication.
- ``FEED_PUBLICATION`` — the feed's publication instant, likewise
  carried inside the payload and pinned the same way.
- ``OBSERVED_FIRST_SEEN`` — the information became available to
  us when we first saw it (e.g. a live page read). The effective
  time must equal the observation instant exactly: nothing
  earlier can be claimed, because first-seen is the earliest
  moment we can prove.

Validation fails closed: a missing effective time or basis, an
effective time after the observation instant, a basis the payload
does not carry, or a payload whose SHA-256 does not match the
envelope's ``payload_sha256`` each make the envelope invalid.

Corrections are **append-only supersede chains, never edits**: a
corrected fact is a NEW envelope whose ``corrections`` list
references the envelope it supersedes (with a reason). The
superseded envelope is never mutated; readers resolve currency by
walking the chain (``chain_status``).

Envelope identity is content-derived: ``envelope_id`` is the
SHA-256 of a canonical identity core (payload hash, fixture,
participants, the two instants, the basis, the provenance source,
and a hash of any extension sections), so identical content maps
to the same id and any post-issuance edit breaks validation.

Honesty contract: an owner receipt is **evidence preservation,
never an evaluation** — it prices nothing, fetches nothing, and
certifies nothing about forecasting skill. It attests only that
these bytes existed, bound to this fixture and these identities,
observed at one instant and effectively available at another, from
this source, with this correction history. Development/verification
use (see ``receipt_dry_run.py``) does not activate any capture
path.
"""
from __future__ import annotations

import base64
import binascii
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path

OWNER_RECEIPT_SCHEMA = "SPORTSEDGE_OWNER_RECEIPT_V1"
OWNER_RECEIPTS_DIRNAME = "owner-receipts"
ENVELOPE_ID_PREFIX = "ownr_"

BASIS_SOURCE_TIMESTAMP = "SOURCE_TIMESTAMP"
BASIS_FEED_PUBLICATION = "FEED_PUBLICATION"
BASIS_OBSERVED_FIRST_SEEN = "OBSERVED_FIRST_SEEN"
EFFECTIVE_AT_BASES = frozenset({
    BASIS_SOURCE_TIMESTAMP, BASIS_FEED_PUBLICATION,
    BASIS_OBSERVED_FIRST_SEEN})
# Bases whose evidence is a timestamp the payload itself carries.
_PAYLOAD_CARRIED_BASES = frozenset({
    BASIS_SOURCE_TIMESTAMP, BASIS_FEED_PUBLICATION})


class OwnerReceiptError(ValueError):
    pass


def _iso(stamp):
    return stamp.astimezone(timezone.utc).isoformat().replace(
        "+00:00", "Z")


def _stamp(value, key):
    """Parse an ISO-8601 timestamp; fail closed unless UTC-aware."""
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise OwnerReceiptError(
            "OWNER_TIMESTAMP_INVALID:" + key) from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise OwnerReceiptError("OWNER_TIMESTAMP_NOT_UTC_AWARE:" + key)
    return stamp.astimezone(timezone.utc)


def _canonical_sha256(obj):
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _envelope_id(core):
    return ENVELOPE_ID_PREFIX + _canonical_sha256(core)


def _normalize_stamp(value, key):
    """Normalize a builder-supplied instant to stored Z-form.

    None passes through as None so validation — not the builder —
    raises the named missing-field error."""
    if value is None:
        return None
    if isinstance(value, str):
        return _iso(_stamp(value, key))
    return _iso(_stamp(value.isoformat(), key))


def _identity_core(envelope):
    """The content the envelope id binds. issued_at is excluded:
    identity is what the envelope attests, not when it was filed."""
    extensions = envelope.get("extensions") or {}
    return {
        "receipt_schema": envelope.get("receipt_schema"),
        "payload_sha256": envelope.get("payload_sha256"),
        "fixture_id": envelope.get("fixture_id"),
        "participants": envelope.get("participants"),
        "observed_at_utc": envelope.get("observed_at_utc"),
        "effective_at_utc": envelope.get("effective_at_utc"),
        "effective_at_basis": envelope.get("effective_at_basis"),
        "effective_at_basis_field": envelope.get(
            "effective_at_basis_field"),
        "provenance_source_name": (envelope.get("provenance") or {})
        .get("source_name"),
        "extensions_sha256": _canonical_sha256(extensions),
    }


def payload_bytes_of(envelope):
    """Decode the envelope's raw payload bytes (exact, pre-hash)."""
    raw = envelope.get("raw_payload")
    if not isinstance(raw, str) or not raw:
        raise OwnerReceiptError("OWNER_PAYLOAD_MISSING")
    if envelope.get("raw_payload_encoding") != "BASE64":
        raise OwnerReceiptError(
            "OWNER_PAYLOAD_ENCODING_INVALID:"
            + str(envelope.get("raw_payload_encoding")))
    try:
        return base64.b64decode(raw.encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError) as exc:
        raise OwnerReceiptError("OWNER_PAYLOAD_NOT_BASE64") from exc


def payload_json_of(envelope):
    """The payload parsed as JSON, or None when it is not JSON."""
    try:
        parsed = json.loads(payload_bytes_of(envelope).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed


def _validate_corrections(envelope):
    corrections = envelope.get("corrections")
    if corrections is None:
        return []
    if not isinstance(corrections, list):
        raise OwnerReceiptError("OWNER_CORRECTIONS_NOT_A_LIST")
    seen = set()
    for entry in corrections:
        if not isinstance(entry, dict):
            raise OwnerReceiptError("OWNER_CORRECTION_NOT_AN_OBJECT")
        ref = entry.get("supersedes_envelope_id")
        if not isinstance(ref, str) or not ref.strip():
            raise OwnerReceiptError("OWNER_CORRECTION_REF_MISSING")
        if ref == envelope.get("envelope_id"):
            raise OwnerReceiptError("OWNER_CORRECTION_SELF_REFERENCE")
        if ref in seen:
            raise OwnerReceiptError(
                "OWNER_CORRECTION_DUPLICATE_REF:" + ref)
        seen.add(ref)
        reason = entry.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise OwnerReceiptError("OWNER_CORRECTION_REASON_MISSING")
    return corrections


def validate_owner_receipt(envelope):
    """Validate one owner receipt envelope. Returns it unchanged.

    Fail-closed on every owner-format rule (see module docstring).
    Raises OwnerReceiptError naming the specific violated rule.
    """
    if not isinstance(envelope, dict):
        raise OwnerReceiptError("OWNER_ENVELOPE_NOT_OBJECT")
    if envelope.get("receipt_schema") != OWNER_RECEIPT_SCHEMA:
        raise OwnerReceiptError(
            "OWNER_SCHEMA_MISMATCH:" + str(envelope.get(
                "receipt_schema")))
    # --- payload: present, decodable, hash-bound -------------------
    raw_bytes = payload_bytes_of(envelope)
    claimed = envelope.get("payload_sha256")
    if not isinstance(claimed, str) or not claimed.strip():
        raise OwnerReceiptError("OWNER_PAYLOAD_SHA256_MISSING")
    if hashlib.sha256(raw_bytes).hexdigest() != claimed:
        raise OwnerReceiptError("OWNER_PAYLOAD_HASH_MISMATCH")
    payload_json = envelope.get("payload_json")
    if payload_json is not None:
        # The convenience parsed copy must be the payload itself,
        # never a paraphrase of it.
        reparsed = payload_json_of(envelope)
        if reparsed != payload_json:
            raise OwnerReceiptError("OWNER_PAYLOAD_JSON_MISMATCH")
    # --- fixture + participant identity ----------------------------
    fixture_id = envelope.get("fixture_id")
    if not isinstance(fixture_id, str) or not fixture_id.strip():
        raise OwnerReceiptError("OWNER_FIXTURE_ID_MISSING")
    participants = envelope.get("participants")
    if not isinstance(participants, list) or not participants:
        raise OwnerReceiptError("OWNER_PARTICIPANTS_MISSING")
    for participant in participants:
        if not isinstance(participant, dict):
            raise OwnerReceiptError("OWNER_PARTICIPANT_NOT_AN_OBJECT")
        pid = participant.get("participant_id")
        if not isinstance(pid, str) or not pid.strip():
            raise OwnerReceiptError("OWNER_PARTICIPANT_ID_MISSING")
    # --- the two instants ------------------------------------------
    if not envelope.get("observed_at_utc"):
        raise OwnerReceiptError("OWNER_OBSERVED_AT_MISSING")
    observed = _stamp(envelope["observed_at_utc"], "observed_at_utc")
    if envelope.get("issued_at_utc"):
        _stamp(envelope["issued_at_utc"], "issued_at_utc")
    if not envelope.get("effective_at_utc"):
        raise OwnerReceiptError("OWNER_EFFECTIVE_AT_MISSING")
    effective = _stamp(envelope["effective_at_utc"],
                       "effective_at_utc")
    basis = envelope.get("effective_at_basis")
    if not basis:
        raise OwnerReceiptError("OWNER_EFFECTIVE_AT_BASIS_MISSING")
    if basis not in EFFECTIVE_AT_BASES:
        raise OwnerReceiptError(
            "OWNER_EFFECTIVE_AT_BASIS_INVALID:" + str(basis))
    if effective > observed:
        # Information cannot have been observed before it became
        # available; an effective time after the observation
        # instant is incoherent, not merely optimistic.
        raise OwnerReceiptError("OWNER_EFFECTIVE_AFTER_OBSERVED")
    basis_field = envelope.get("effective_at_basis_field")
    if basis in _PAYLOAD_CARRIED_BASES:
        # The effective time is pinned to a timestamp the payload
        # itself carries — the only construction under which an
        # effective time earlier than the observation instant can
        # be evidenced at all.
        if not isinstance(basis_field, str) or not basis_field.strip():
            raise OwnerReceiptError(
                "OWNER_EFFECTIVE_BASIS_FIELD_MISSING")
        payload = payload_json_of(envelope)
        if not isinstance(payload, dict):
            raise OwnerReceiptError(
                "OWNER_EFFECTIVE_BASIS_PAYLOAD_NOT_JSON")
        if basis_field not in payload:
            raise OwnerReceiptError(
                "OWNER_EFFECTIVE_BASIS_FIELD_ABSENT_FROM_PAYLOAD:"
                + basis_field)
        carried = _stamp(payload[basis_field],
                         "payload." + basis_field)
        if carried != effective:
            raise OwnerReceiptError(
                "OWNER_EFFECTIVE_AT_BASIS_MISMATCH: effective_at_utc "
                "must equal the payload-carried " + basis_field)
    else:  # OBSERVED_FIRST_SEEN
        if basis_field:
            raise OwnerReceiptError(
                "OWNER_EFFECTIVE_BASIS_FIELD_UNEXPECTED:"
                + str(basis_field))
        if effective != observed:
            raise OwnerReceiptError(
                "OWNER_EFFECTIVE_FIRST_SEEN_MISMATCH: first-seen "
                "availability is the observation instant itself; an "
                "earlier effective time is unprovable under this "
                "basis")
    # --- provenance -------------------------------------------------
    provenance = envelope.get("provenance")
    if not isinstance(provenance, dict):
        raise OwnerReceiptError("OWNER_PROVENANCE_MISSING")
    if not str(provenance.get("source_name") or "").strip():
        raise OwnerReceiptError("OWNER_PROVENANCE_SOURCE_NAME_MISSING")
    if not str(provenance.get("retrieval_path") or "").strip():
        raise OwnerReceiptError(
            "OWNER_PROVENANCE_RETRIEVAL_PATH_MISSING")
    # --- corrections + identity ------------------------------------
    _validate_corrections(envelope)
    if envelope.get("envelope_id") != _envelope_id(
            _identity_core(envelope)):
        raise OwnerReceiptError("OWNER_ENVELOPE_ID_MISMATCH")
    return envelope


def build_owner_receipt(raw_payload, *, fixture_id, participants,
                        observed_at, effective_at, effective_at_basis,
                        effective_at_basis_field=None, provenance,
                        corrections=None, extensions=None, now=None):
    """Assemble and validate one owner receipt envelope.

    ``raw_payload`` is the exact payload bytes (bytes or str); they
    are embedded byte-exactly (base64) and hash-bound. The builder
    validates before returning: an envelope that violates any
    owner-format rule is never issued.
    """
    if isinstance(raw_payload, str):
        raw_bytes = raw_payload.encode("utf-8")
    else:
        raw_bytes = bytes(raw_payload)
    issued = now or datetime.now(timezone.utc)
    if issued.tzinfo is None or issued.utcoffset() is None:
        raise OwnerReceiptError("OWNER_CLOCK_NOT_UTC_AWARE")
    envelope = {
        "receipt_schema": OWNER_RECEIPT_SCHEMA,
        "envelope_id": None,  # bound below, once content is fixed
        "issued_at_utc": _normalize_stamp(issued, "issued_at_utc"),
        "fixture_id": fixture_id,
        "participants": participants,
        "raw_payload": base64.b64encode(raw_bytes).decode("ascii"),
        "raw_payload_encoding": "BASE64",
        "payload_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "payload_json": None,
        "observed_at_utc": _normalize_stamp(
            observed_at, "observed_at_utc"),
        "effective_at_utc": _normalize_stamp(
            effective_at, "effective_at_utc"),
        "effective_at_basis": effective_at_basis,
        "effective_at_basis_field": effective_at_basis_field,
        "provenance": provenance,
        "corrections": list(corrections or []),
        "extensions": dict(extensions or {}),
    }
    try:
        envelope["payload_json"] = json.loads(
            raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        envelope["payload_json"] = None
    envelope["envelope_id"] = _envelope_id(_identity_core(envelope))
    return validate_owner_receipt(envelope)


def build_correction(original, raw_payload, *, reason, **kwargs):
    """Issue the envelope that supersedes ``original``.

    The original is never edited: the new envelope's corrections
    list carries the original's own correction history forward and
    appends a reference to the original with ``reason``. All other
    fields come from ``kwargs`` (the corrected evidence may have a
    new payload, fixture binding, instants, and provenance).
    """
    validate_owner_receipt(original)
    if not isinstance(reason, str) or not reason.strip():
        raise OwnerReceiptError("OWNER_CORRECTION_REASON_MISSING")
    history = [dict(entry)
               for entry in original.get("corrections") or []]
    history.append({"supersedes_envelope_id": original["envelope_id"],
                    "reason": reason})
    return build_owner_receipt(raw_payload, corrections=history,
                               **kwargs)


def chain_status(envelope_id, envelopes):
    """CURRENT / SUPERSEDED / UNKNOWN for one envelope id among a set.

    An envelope is SUPERSEDED when some other envelope's
    corrections list references it. Currency is derived by walking
    references; stored envelopes are never edited to record it.
    """
    ids = {env.get("envelope_id") for env in envelopes}
    if envelope_id not in ids:
        return "UNKNOWN"
    for env in envelopes:
        for entry in env.get("corrections") or []:
            if entry.get("supersedes_envelope_id") == envelope_id:
                return "SUPERSEDED"
    return "CURRENT"


# ------------------------------------------------------------- persistence

def owner_receipts_dir(root):
    return Path(root) / OWNER_RECEIPTS_DIRNAME


def owner_receipt_path(root, envelope_id):
    return owner_receipts_dir(root) / (str(envelope_id) + ".json")


def _fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_owner_receipt(root, envelope):
    """Write one envelope write-once, fsync'd. Returns (path, dup).

    A byte-identical re-issuance of the same envelope is a
    duplicate (returned as-is); an existing file with different
    content under the same id is refused — an id collision or a
    tampered store, never silently blessed.
    """
    validate_owner_receipt(envelope)
    directory = owner_receipts_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (envelope["envelope_id"] + ".json")
    blob = json.dumps(envelope, indent=2, sort_keys=True) + "\n"
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(blob)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_dir(directory)
    except FileExistsError:
        # A re-issuance of the same attested content (same id —
        # the id binds the content core, issuance instant aside)
        # is a benign duplicate. Anything else under this id — an
        # invalid stored envelope, or a different id — is a
        # collision or a tampered store: refuse.
        try:
            existing = read_owner_receipt(path)
        except OwnerReceiptError as exc:
            raise OwnerReceiptError(
                "OWNER_RECEIPT_ID_COLLISION:" + str(path)) from exc
        if existing["envelope_id"] != envelope["envelope_id"]:
            raise OwnerReceiptError(
                "OWNER_RECEIPT_ID_COLLISION:" + str(path))
        return path, True
    return path, False


def read_owner_receipt(path):
    """Load and fully validate one stored envelope (hash re-verified
    against the embedded raw payload bytes)."""
    envelope = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_owner_receipt(envelope)


def list_owner_receipts(root):
    """Every stored envelope under ``root``, validated, id order."""
    directory = owner_receipts_dir(root)
    if not directory.is_dir():
        return []
    return [read_owner_receipt(path)
            for path in sorted(directory.glob("*.json"))]
