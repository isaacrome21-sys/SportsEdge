"""Deterministic policy-bundle hashing for SportsEdge audit/replay.

The bundle hash binds the exact sport Truth Gate, validation, quote synchronization,
benchmark, exposure/evidence/degrade governance and any other named policy artifacts.
A live/historical decision must not claim a policy bundle it cannot reproduce.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Iterable


class PolicyBundleError(ValueError):
    pass


def canonical_json_sha256(path: str | Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise PolicyBundleError(f"POLICY_FILE_MISSING:{p}")
    try:
        value = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        raise PolicyBundleError(f"POLICY_JSON_INVALID:{p}") from exc
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return sha256(raw).hexdigest()


@dataclass(frozen=True)
class PolicyBundle:
    bundle_id: str
    artifacts: tuple[tuple[str, str], ...]

    def validate(self) -> "PolicyBundle":
        if not self.bundle_id:
            raise PolicyBundleError("POLICY_BUNDLE_ID_REQUIRED")
        names = [name for name, _ in self.artifacts]
        if not names or len(names) != len(set(names)):
            raise PolicyBundleError("POLICY_BUNDLE_ARTIFACT_NAMES_INVALID")
        for name, digest in self.artifacts:
            if not name or len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest.lower()):
                raise PolicyBundleError("POLICY_BUNDLE_ARTIFACT_SHA_INVALID")
        return self

    def content_hash(self) -> str:
        self.validate()
        payload = {"bundle_id": self.bundle_id, "artifacts": list(self.artifacts)}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        return sha256(raw).hexdigest()


def build_policy_bundle(bundle_id: str, paths: Iterable[tuple[str, str | Path]]) -> PolicyBundle:
    artifacts = tuple(sorted((str(name), canonical_json_sha256(path)) for name, path in paths))
    return PolicyBundle(str(bundle_id), artifacts).validate()
