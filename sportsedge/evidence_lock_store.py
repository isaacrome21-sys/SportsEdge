"""Write-once evidence storage interface (S3 Object Lock COMPLIANCE).

Status: NOT ACTIVATED. No bucket is provisioned, no credentials exist in the
repository, and nothing in the repo calls this module. ``S3ObjectLockWriter``
needs an injected boto3-compatible client (credentials come from the host's
secret store, never from code or config) AND ``enabled=True``.

Contract: every object is written once, with SHA-256 checksum, COMPLIANCE
retention and an explicit retain-until date; overwrites and deletes are refused
by the interface (and by the bucket itself once Object Lock is on).
"""
from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

LOCK_MODE = "COMPLIANCE"
MIN_RETENTION_DAYS = 3650
_KEY = re.compile(r"^[a-z0-9][a-z0-9._/-]{0,511}$")


class LockStoreError(ValueError):
    pass


@dataclass(frozen=True)
class LockReceipt:
    key: str
    sha256: str
    version_id: str
    retain_until: datetime
    mode: str


class ObjectLockWriter(Protocol):
    def put_locked(self, key: str, body: bytes, *, now: datetime | None = None) -> LockReceipt: ...


def _check(key: str, body: bytes, retention_days: int, mode: str) -> str:
    if not isinstance(key, str) or not _KEY.match(key) or ".." in key:
        raise LockStoreError("bad key")
    if not isinstance(body, (bytes, bytearray)) or not body:
        raise LockStoreError("empty body")
    if mode != LOCK_MODE:
        raise LockStoreError("only COMPLIANCE mode is allowed")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < MIN_RETENTION_DAYS:
        raise LockStoreError("retention below approved minimum")
    return hashlib.sha256(body).hexdigest()


def _check_policy(mode: Any, retention_days: Any) -> None:
    if mode != LOCK_MODE:
        raise LockStoreError("only COMPLIANCE mode is allowed")
    if isinstance(retention_days, bool) or not isinstance(retention_days, int) or retention_days < MIN_RETENTION_DAYS:
        raise LockStoreError("retention below approved minimum")


_BUCKET = re.compile(r"^[a-z0-9][a-z0-9.-]{2,62}$")


@dataclass(frozen=True)
class ObjectLockSettings:
    bucket: str
    mode: str
    retention_days: int


def object_lock_settings(block: Any) -> ObjectLockSettings:
    """Strictly validate the ``object_lock`` config block (t130). Refuses anything
    missing, mistyped, non-COMPLIANCE or with retention < 3650 days."""
    if not isinstance(block, Mapping):
        raise LockStoreError("object_lock config missing")
    b = block.get("bucket")
    if not isinstance(b, str):
        raise LockStoreError("object_lock.bucket missing")
    name = b[len("s3://"):] if b.startswith("s3://") else b
    if not _BUCKET.match(name) or ".." in name:
        raise LockStoreError("bad bucket name")
    _check_policy(block.get("mode"), block.get("retention_days"))
    return ObjectLockSettings(name, block["mode"], block["retention_days"])


class InMemoryLockWriter:
    """Test double with Object Lock semantics: write-once, no delete."""

    def __init__(self, retention_days: int = MIN_RETENTION_DAYS, mode: str = LOCK_MODE):
        _check_policy(mode, retention_days)
        self.retention_days, self.mode = retention_days, mode
        self._objs: dict[str, tuple[bytes, LockReceipt]] = {}

    def put_locked(self, key, body, *, now=None):
        sha = _check(key, body, self.retention_days, self.mode)
        if key in self._objs:
            raise LockStoreError("object exists; overwrite refused")
        now = now or datetime.now(timezone.utc)
        rec = LockReceipt(key, sha, f"v{len(self._objs) + 1}", now + timedelta(days=self.retention_days), self.mode)
        self._objs[key] = (bytes(body), rec)
        return rec

    def get(self, key: str) -> bytes:
        return self._objs[key][0]

    def delete(self, key: str) -> None:
        raise LockStoreError("delete refused: object is retention-locked")


class S3ObjectLockWriter:
    """S3 Object Lock writer. Refuses unless enabled and given a client."""

    def __init__(self, bucket: str, client: Any, *, enabled: bool = False,
                 retention_days: int = MIN_RETENTION_DAYS, mode: str = LOCK_MODE):
        if not enabled:
            raise LockStoreError("object-lock writer not activated")
        if client is None:
            raise LockStoreError("client required (credentials via host secret store)")
        if not isinstance(bucket, str) or not _BUCKET.match(bucket):
            raise LockStoreError("bad bucket name")
        _check_policy(mode, retention_days)
        self.bucket, self.client, self.retention_days, self.mode = bucket, client, retention_days, mode

    @classmethod
    def from_config(cls, block: Any, client: Any, *, enabled: bool = False) -> "S3ObjectLockWriter":
        st = object_lock_settings(block)
        return cls(st.bucket, client, enabled=enabled, retention_days=st.retention_days, mode=st.mode)

    def verify_bucket(self) -> None:
        try:
            cfg = self.client.get_object_lock_configuration(Bucket=self.bucket)["ObjectLockConfiguration"]
            ver = self.client.get_bucket_versioning(Bucket=self.bucket)
        except LockStoreError:
            raise
        except Exception as e:  # fail closed on any client/shape error
            raise LockStoreError(f"bucket preflight failed: {type(e).__name__}") from e
        if not isinstance(cfg, Mapping) or cfg.get("ObjectLockEnabled") != "Enabled":
            raise LockStoreError("bucket does not have Object Lock enabled")
        if not isinstance(ver, Mapping) or ver.get("Status") != "Enabled":
            raise LockStoreError("bucket versioning not enabled")
        dr = (cfg.get("Rule") or {}).get("DefaultRetention") if isinstance(cfg.get("Rule"), Mapping) else None
        if not isinstance(dr, Mapping) or dr.get("Mode") != LOCK_MODE:
            raise LockStoreError("bucket default retention is not COMPLIANCE")
        days = dr.get("Days")
        years = dr.get("Years")
        eff = (days if isinstance(days, int) and not isinstance(days, bool) else
               years * 365 if isinstance(years, int) and not isinstance(years, bool) else None)
        if eff is None or eff < MIN_RETENTION_DAYS:
            raise LockStoreError("bucket default retention below approved minimum")

    def put_locked(self, key, body, *, now=None):
        sha = _check(key, body, self.retention_days, self.mode)
        # Validate the *actual target bucket* on every write. A caller cannot
        # skip the Object Lock + versioning preflight by omitting verify_bucket().
        self.verify_bucket()
        current = datetime.now(timezone.utc)
        if now is not None:
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise LockStoreError("retention clock must be timezone-aware")
            if now < current - timedelta(seconds=30):
                raise LockStoreError("retention clock is stale")
        now = now or current
        until = now + timedelta(days=self.retention_days)
        try:
            r = self.client.put_object(
                Bucket=self.bucket, Key=key, Body=bytes(body),
                ChecksumSHA256=base64.b64encode(bytes.fromhex(sha)).decode(),
                ObjectLockMode=self.mode, ObjectLockRetainUntilDate=until,
                IfNoneMatch="*")
        except Exception as e:  # e.g. 412 PreconditionFailed: key exists
            raise LockStoreError(f"write refused (overwrite or store error): {type(e).__name__}") from e
        if not isinstance(r, Mapping):
            raise LockStoreError("bad store response")
        vid = r.get("VersionId")
        if not vid:
            raise LockStoreError("no VersionId returned; versioning/Object Lock not effective")
        back = r.get("ChecksumSHA256")
        if back is not None and back != base64.b64encode(bytes.fromhex(sha)).decode():
            raise LockStoreError("checksum mismatch from store")
        return LockReceipt(key, sha, vid, until, self.mode)
