"""Bind an anchor payload's storage location and carrier into the leaf the TSA layer stamps.

Coordination (#2219, #2218): Muse's ``sportsedge/mlb_receipt_anchor_publisher.py`` (registry
``MLB_RECEIPT_JOURNAL_ANCHOR_V1``) reportedly derives ``anchor_id`` from the payload alone,
so the same id can be presented from any storage location or by any carrier.  The dual-TSA
layer (the RFC 3161 anchor module) stamps ``batch_root(leaves)`` where each leaf is a
lowercase 64-hex SHA-256.  Any payload digest can therefore be stamped as-is; this module
adds an optional, domain-separated *bound leaf* so a TSA token also commits to where the
payload lives and how it was carried.  It does not replace or re-encode the payload, and it
creates no parallel envelope: the publisher's payload digest is an input, unchanged.

Code only.  No network, no activation, no admission authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

BINDING_DOMAIN = "SPORTSEDGE_ANCHOR_LEAF_BINDING_V1"
KNOWN_SCHEMAS = frozenset({"MLB_RECEIPT_JOURNAL_ANCHOR_V1"})
KNOWN_CARRIERS = frozenset({"RFC3161_TSA", "OPENTIMESTAMPS", "GIT_RECORDS_BRANCH", "S3_OBJECT_LOCK"})

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Location must be a canonical URI-like string: scheme://authority/path, no whitespace,
# no query/fragment, no dot segments, no trailing slash.
_LOCATION = re.compile(r"^(s3|git|https|file)://[A-Za-z0-9._\-]+(/[A-Za-z0-9._\-~@:+=,]+)+$")


class BindingError(ValueError):
    pass


@dataclass(frozen=True)
class BoundLeaf:
    schema: str
    payload_sha256: str
    location: str
    carrier: str
    leaf: str           # hex SHA-256 to pass to the anchor module's batch_root

    def as_record(self) -> dict:
        return {"domain": BINDING_DOMAIN, "schema": self.schema,
                "payload_sha256": self.payload_sha256, "location": self.location,
                "carrier": self.carrier, "leaf": self.leaf}


def _canon(schema: str, payload_sha256: str, location: str, carrier: str) -> bytes:
    return json.dumps({"carrier": carrier, "domain": BINDING_DOMAIN, "location": location,
                       "payload_sha256": payload_sha256, "schema": schema},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _check(schema, payload_sha256, location, carrier) -> None:
    if schema not in KNOWN_SCHEMAS:
        raise BindingError(f"UNKNOWN_SCHEMA:{schema!r}")
    if not isinstance(payload_sha256, str) or not _HEX64.match(payload_sha256):
        raise BindingError("PAYLOAD_DIGEST_NOT_LOWER_HEX64")
    if not isinstance(location, str) or not _LOCATION.match(location) or "/./" in location \
            or "/../" in location or location.endswith(("/.", "/..")):
        raise BindingError("LOCATION_NOT_CANONICAL")
    if carrier not in KNOWN_CARRIERS:
        raise BindingError(f"UNKNOWN_CARRIER:{carrier!r}")
    if location.startswith("s3://") or carrier == "S3_OBJECT_LOCK":
        # Owner ruling 2026-10-14: any S3-backed binding MUST carry the object VersionId.
        raise BindingError("S3_REQUIRES_VERSIONED_BINDING")


def bind_leaf(*, schema: str, payload_sha256: str, location: str, carrier: str) -> BoundLeaf:
    """Return the domain-separated leaf committing payload digest + location + carrier."""
    _check(schema, payload_sha256, location, carrier)
    leaf = hashlib.sha256(_canon(schema, payload_sha256, location, carrier)).hexdigest()
    return BoundLeaf(schema, payload_sha256, location, carrier, leaf)


def verify_bound_leaf(record: dict, *, expected_payload_sha256: str, observed_location: str,
                      observed_carrier: str) -> tuple[bool, str]:
    """Fail-closed check that a stamped leaf matches what was actually fetched, where, and how."""
    try:
        if not isinstance(record, dict) or record.get("domain") != BINDING_DOMAIN:
            return False, "WRONG_DOMAIN"
        rebuilt = bind_leaf(schema=record.get("schema"), payload_sha256=record.get("payload_sha256"),
                            location=record.get("location"), carrier=record.get("carrier"))
    except BindingError as e:
        return False, str(e)
    if rebuilt.leaf != record.get("leaf"):
        return False, "LEAF_MISMATCH"
    if rebuilt.payload_sha256 != expected_payload_sha256:
        return False, "PAYLOAD_MISMATCH"
    if rebuilt.location != observed_location:
        return False, "LOCATION_MISMATCH"
    if rebuilt.carrier != observed_carrier:
        return False, "CARRIER_MISMATCH"
    return True, "OK"


# ---------------------------------------------------------------------------------------
# t141: S3 object-version binding (owner ruling 2026-10-14, MANDATORY for S3-backed admission)
#
# The leaf commits bucket, exact object key, S3 VersionId, payload SHA-256 (never an ETag),
# and the receipt + anchor identifiers. Verification re-fetches THAT version through an
# injected client (``get_object(Bucket=, Key=, VersionId=)``, boto3-shaped) and recomputes
# SHA-256 over the returned bytes. Bindings are recorded in an append-only, fsynced,
# flock-serialized ledger; a (bucket, key, receipt, anchor) identity can be bound once and
# never rebound. Code only: no network, no AWS credentials, no activation.
# ---------------------------------------------------------------------------------------
import fcntl
import os
import stat
from pathlib import Path
from typing import Any, Callable

S3_BINDING_DOMAIN = "SPORTSEDGE_ANCHOR_LEAF_BINDING_S3_VERSIONED_V1"
MAX_S3_OBJECT_BYTES = 64 * 1024 * 1024
_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9]$")
_VERSION_ID = re.compile(r"^[A-Za-z0-9._\-+/=]{1,1024}$")
_IDENT = re.compile(r"^[A-Za-z0-9._:\-]{1,128}$")
_MD5_HEX = re.compile(r"^[0-9a-fA-F]{32}(-[0-9]+)?$")


@dataclass(frozen=True)
class S3BoundLeaf:
    schema: str
    bucket: str
    key: str
    version_id: str
    payload_sha256: str
    receipt_id: str
    anchor_id: str
    leaf: str

    def as_record(self) -> dict:
        return {"domain": S3_BINDING_DOMAIN, "schema": self.schema, "carrier": "S3_OBJECT_LOCK",
                "bucket": self.bucket, "key": self.key, "version_id": self.version_id,
                "payload_sha256": self.payload_sha256, "receipt_id": self.receipt_id,
                "anchor_id": self.anchor_id, "leaf": self.leaf}


def _check_key(key: Any) -> None:
    if not isinstance(key, str) or not key or len(key.encode("utf-8")) > 1024:
        raise BindingError("S3_KEY_INVALID")
    if key.startswith("/") or key.endswith("/") or "//" in key \
            or any(ord(c) < 0x20 or ord(c) == 0x7f for c in key):
        raise BindingError("S3_KEY_INVALID")
    if any(seg in (".", "..") for seg in key.split("/")):
        raise BindingError("S3_KEY_INVALID")


def _check_s3(schema, bucket, key, version_id, payload_sha256, receipt_id, anchor_id) -> None:
    if schema not in KNOWN_SCHEMAS:
        raise BindingError(f"UNKNOWN_SCHEMA:{schema!r}")
    if not isinstance(bucket, str) or not _BUCKET.match(bucket) or ".." in bucket:
        raise BindingError("S3_BUCKET_INVALID")
    _check_key(key)
    if version_id is None or not isinstance(version_id, str) or version_id == "":
        raise BindingError("S3_VERSION_ID_MISSING")
    if version_id == "null":
        # S3 reports the literal "null" for objects written while versioning was off.
        raise BindingError("S3_VERSION_ID_NULL")
    if not _VERSION_ID.match(version_id):
        raise BindingError("S3_VERSION_ID_INVALID")
    if not isinstance(payload_sha256, str):
        raise BindingError("PAYLOAD_DIGEST_NOT_LOWER_HEX64")
    if _MD5_HEX.match(payload_sha256.strip('"')):
        raise BindingError("ETAG_NOT_ACCEPTED_AS_DIGEST")
    if not _HEX64.match(payload_sha256):
        raise BindingError("PAYLOAD_DIGEST_NOT_LOWER_HEX64")
    for name, v in (("RECEIPT_ID", receipt_id), ("ANCHOR_ID", anchor_id)):
        if not isinstance(v, str) or not _IDENT.match(v):
            raise BindingError(f"{name}_INVALID")


def _canon_s3(schema, bucket, key, version_id, payload_sha256, receipt_id, anchor_id) -> bytes:
    return json.dumps({"anchor_id": anchor_id, "bucket": bucket, "carrier": "S3_OBJECT_LOCK",
                       "domain": S3_BINDING_DOMAIN, "key": key, "payload_sha256": payload_sha256,
                       "receipt_id": receipt_id, "schema": schema, "version_id": version_id},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def bind_s3_leaf(*, schema: str, bucket: str, key: str, version_id: str, payload_sha256: str,
                 receipt_id: str, anchor_id: str) -> S3BoundLeaf:
    _check_s3(schema, bucket, key, version_id, payload_sha256, receipt_id, anchor_id)
    leaf = hashlib.sha256(_canon_s3(schema, bucket, key, version_id, payload_sha256,
                                    receipt_id, anchor_id)).hexdigest()
    return S3BoundLeaf(schema, bucket, key, version_id, payload_sha256, receipt_id, anchor_id, leaf)


_S3_FIELDS = ("schema", "bucket", "key", "version_id", "payload_sha256", "receipt_id", "anchor_id")
_S3_RECORD_KEYS = frozenset(_S3_FIELDS) | {"domain", "carrier", "leaf"}


def _rebuild_s3(record: Any) -> S3BoundLeaf:
    if not isinstance(record, dict) or record.get("domain") != S3_BINDING_DOMAIN:
        raise BindingError("WRONG_DOMAIN")
    if set(record) != _S3_RECORD_KEYS or record.get("carrier") != "S3_OBJECT_LOCK":
        raise BindingError("S3_RECORD_SHAPE_INVALID")
    rebuilt = bind_s3_leaf(**{f: record.get(f) for f in _S3_FIELDS})
    if rebuilt.leaf != record.get("leaf"):
        raise BindingError("LEAF_MISMATCH")
    return rebuilt


def _read_body(body: Any) -> bytes:
    data = body.read(MAX_S3_OBJECT_BYTES + 1) if hasattr(body, "read") else body
    if not isinstance(data, (bytes, bytearray)):
        raise BindingError("S3_BODY_INVALID")
    if len(data) > MAX_S3_OBJECT_BYTES:
        raise BindingError("S3_BODY_TOO_LARGE")
    return bytes(data)


def verify_s3_bound_leaf(record: dict, *, s3_client: Any, expected_payload_sha256: str,
                         expected_receipt_id: str, expected_anchor_id: str) -> tuple[bool, str]:
    """Fail-closed: rebuild the leaf, fetch EXACTLY the bound version, hash the bytes.

    Refuses: missing/"null"/invalid VersionId, ETag offered as digest, response for a
    different version (or no version), SHA-256 mismatch, receipt/anchor substitution,
    any client error. Never raises.
    """
    try:
        rec = _rebuild_s3(record)
    except BindingError as e:
        return False, str(e)
    except Exception:
        return False, "S3_RECORD_SHAPE_INVALID"
    if rec.payload_sha256 != expected_payload_sha256:
        return False, "PAYLOAD_MISMATCH"
    if rec.receipt_id != expected_receipt_id:
        return False, "RECEIPT_ID_MISMATCH"
    if rec.anchor_id != expected_anchor_id:
        return False, "ANCHOR_ID_MISMATCH"
    try:
        resp = s3_client.get_object(Bucket=rec.bucket, Key=rec.key, VersionId=rec.version_id)
    except Exception as e:  # any transport/auth/NoSuchVersion error fails closed
        return False, f"S3_FETCH_FAILED:{type(e).__name__}"
    if not isinstance(resp, dict):
        return False, "S3_RESPONSE_INVALID"
    got_version = resp.get("VersionId")
    if got_version is None or got_version in ("", "null"):
        return False, "S3_RESPONSE_VERSION_MISSING"
    if got_version != rec.version_id:
        return False, "S3_UNEXPECTED_VERSION"
    try:
        data = _read_body(resp.get("Body"))
    except BindingError as e:
        return False, str(e)
    except Exception:
        return False, "S3_BODY_INVALID"
    actual = hashlib.sha256(data).hexdigest()
    if actual != rec.payload_sha256:
        return False, "S3_PAYLOAD_SHA256_MISMATCH"
    etag = str(resp.get("ETag", "")).strip('"').lower()
    if etag and etag == rec.payload_sha256:
        return False, "ETAG_NOT_ACCEPTED_AS_DIGEST"   # defensive; cannot coincide honestly
    return True, "OK"


class S3BindingLedger:
    """Append-only, immutable record of S3 version bindings (one line per binding).

    Each identity (bucket, key, receipt_id, anchor_id) may be bound exactly once; a second
    append for the same identity is refused even if identical. Every read re-verifies every
    line; any corruption, torn tail, unknown field or leaf mismatch fails closed.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _open(self, flags: int) -> int:
        fd = os.open(self.path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise BindingError("S3_LEDGER_PATH_UNSAFE")
        return fd

    def _parse(self, raw: bytes) -> list[S3BoundLeaf]:
        if raw and not raw.endswith(b"\n"):
            raise BindingError("S3_LEDGER_TORN_TAIL")
        out, seen = [], set()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise BindingError("S3_LEDGER_CORRUPT") from None
        for line in text.splitlines():
            try:
                rec = _rebuild_s3(json.loads(line))
            except (ValueError, TypeError) as e:
                raise BindingError(f"S3_LEDGER_CORRUPT:{e}") from None
            ident = (rec.bucket, rec.key, rec.receipt_id, rec.anchor_id)
            if ident in seen:
                raise BindingError("S3_LEDGER_DUPLICATE_IDENTITY")
            seen.add(ident)
            out.append(rec)
        return out

    def entries(self) -> list[S3BoundLeaf]:
        try:
            fd = self._open(os.O_RDONLY)
        except FileNotFoundError:
            return []
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            chunks = []
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                chunks.append(b)
        finally:
            os.close(fd)
        return self._parse(b"".join(chunks))

    def append(self, leaf: S3BoundLeaf) -> None:
        if not isinstance(leaf, S3BoundLeaf):
            raise BindingError("S3_LEDGER_ENTRY_INVALID")
        _rebuild_s3(leaf.as_record())   # re-validate; frozen dataclass can't be mutated
        line = (json.dumps(leaf.as_record(), sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True) + "\n").encode("ascii")
        fd = self._open(os.O_RDWR | os.O_CREAT | os.O_APPEND)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.lseek(fd, 0, os.SEEK_SET)
            chunks = []
            while True:
                b = os.read(fd, 1 << 20)
                if not b:
                    break
                chunks.append(b)
            existing = self._parse(b"".join(chunks))
            ident = (leaf.bucket, leaf.key, leaf.receipt_id, leaf.anchor_id)
            if any((e.bucket, e.key, e.receipt_id, e.anchor_id) == ident for e in existing):
                raise BindingError("S3_BINDING_IMMUTABLE")
            pending = memoryview(line)
            while pending:
                n = os.write(fd, pending)
                if n <= 0:
                    raise BindingError("S3_LEDGER_WRITE_INCOMPLETE")
                pending = pending[n:]
            os.fsync(fd)
        finally:
            os.close(fd)
        dfd = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)


def admit_s3_bound_payload(record: dict, *, ledger: S3BindingLedger, s3_client: Any,
                           expected_payload_sha256: str, expected_receipt_id: str,
                           expected_anchor_id: str) -> tuple[bool, str]:
    """S3-backed admission precondition: the exact binding must be in the ledger AND verify live.

    This does not admit evidence on its own (admission stays gated by the dual-TSA gate and
    the committed switch); it is the S3 version-binding leg. Never raises.
    """
    try:
        rec = _rebuild_s3(record)
        entries = ledger.entries()
    except BindingError as e:
        return False, str(e)
    except OSError as e:
        return False, f"S3_LEDGER_UNREADABLE:{type(e).__name__}"
    except Exception:
        return False, "S3_RECORD_SHAPE_INVALID"
    if rec not in entries:
        same = [e for e in entries if (e.bucket, e.key, e.receipt_id, e.anchor_id)
                == (rec.bucket, rec.key, rec.receipt_id, rec.anchor_id)]
        return False, "S3_BINDING_DIFFERS_FROM_LEDGER" if same else "S3_BINDING_NOT_IN_LEDGER"
    return verify_s3_bound_leaf(record, s3_client=s3_client,
                                expected_payload_sha256=expected_payload_sha256,
                                expected_receipt_id=expected_receipt_id,
                                expected_anchor_id=expected_anchor_id)
