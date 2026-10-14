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
from typing import Any, Protocol

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


class InMemoryLockWriter:
    """Test double with Object Lock semantics: write-once, no delete."""

    def __init__(self, retention_days: int = MIN_RETENTION_DAYS, mode: str = LOCK_MODE):
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
        if not isinstance(bucket, str) or not re.match(r"^[a-z0-9][a-z0-9.-]{2,62}$", bucket):
            raise LockStoreError("bad bucket name")
        self.bucket, self.client, self.retention_days, self.mode = bucket, client, retention_days, mode

    def verify_bucket(self) -> None:
        cfg = self.client.get_object_lock_configuration(Bucket=self.bucket)["ObjectLockConfiguration"]
        if cfg.get("ObjectLockEnabled") != "Enabled":
            raise LockStoreError("bucket does not have Object Lock enabled")
        ver = self.client.get_bucket_versioning(Bucket=self.bucket)
        if ver.get("Status") != "Enabled":
            raise LockStoreError("bucket versioning not enabled")

    def put_locked(self, key, body, *, now=None):
        sha = _check(key, body, self.retention_days, self.mode)
        now = now or datetime.now(timezone.utc)
        until = now + timedelta(days=self.retention_days)
        r = self.client.put_object(
            Bucket=self.bucket, Key=key, Body=bytes(body),
            ChecksumSHA256=base64.b64encode(bytes.fromhex(sha)).decode(),
            ObjectLockMode=self.mode, ObjectLockRetainUntilDate=until,
            IfNoneMatch="*")
        vid = r.get("VersionId")
        if not vid:
            raise LockStoreError("no VersionId returned; versioning/Object Lock not effective")
        back = r.get("ChecksumSHA256")
        if back is not None and back != base64.b64encode(bytes.fromhex(sha)).decode():
            raise LockStoreError("checksum mismatch from store")
        return LockReceipt(key, sha, vid, until, self.mode)
