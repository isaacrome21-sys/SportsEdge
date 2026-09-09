#!/usr/bin/env python3
"""Verify a public MLB freeze manifest against a private raw-byte checkout."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.odds_api_frozen import MANIFEST_SCHEMA, load_public_manifest, raw_response_sha256  # noqa: E402

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _manifest_sha256(payload: dict) -> str:
    body = dict(payload)
    body.pop("manifest_sha256", None)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--private-root", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    try:
        manifest_raw = args.manifest.read_bytes()
        payload = json.loads(manifest_raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("MLB_FREEZE_MANIFEST_UNREADABLE") from exc
    if not isinstance(payload, dict):
        raise SystemExit("MLB_FREEZE_MANIFEST_MAPPING_REQUIRED")
    if payload.get("schema_version") != MANIFEST_SCHEMA:
        raise SystemExit("MLB_FREEZE_MANIFEST_SCHEMA_INVALID")
    if payload.get("provider") != "THE_ODDS_API" or payload.get("sport") != "mlb":
        raise SystemExit("MLB_FREEZE_MANIFEST_PROVIDER_OR_SPORT_INVALID")
    expected_manifest_sha = str(payload.get("manifest_sha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(expected_manifest_sha):
        raise SystemExit("MLB_FREEZE_MANIFEST_SHA256_INVALID")
    actual_manifest_sha = _manifest_sha256(payload)
    if actual_manifest_sha != expected_manifest_sha:
        raise SystemExit("MLB_FREEZE_MANIFEST_SHA256_MISMATCH")

    entries = load_public_manifest(payload)
    if payload.get("response_count") != len(entries):
        raise SystemExit("MLB_FREEZE_RESPONSE_COUNT_MISMATCH")

    private_root = args.private_root.resolve()
    verified: list[dict[str, object]] = []
    for request_sha, entry in sorted(entries.items()):
        path = (private_root / entry.private_path).resolve()
        try:
            path.relative_to(private_root)
        except ValueError as exc:
            raise SystemExit("MLB_FREEZE_PRIVATE_PATH_ESCAPE") from exc
        if not path.is_file():
            raise SystemExit(f"MLB_FREEZE_PRIVATE_BYTES_MISSING:{entry.private_path}")
        raw = path.read_bytes()
        if len(raw) != entry.byte_length:
            raise SystemExit(f"MLB_FREEZE_PRIVATE_BYTE_LENGTH_MISMATCH:{entry.private_path}")
        if raw_response_sha256(raw) != entry.response_sha256:
            raise SystemExit(f"MLB_FREEZE_PRIVATE_SHA256_MISMATCH:{entry.private_path}")
        verified.append({
            "request_sha256": request_sha,
            "response_sha256": entry.response_sha256,
            "byte_length": entry.byte_length,
        })

    report = {
        "schema_version": 1,
        "status": "PASS",
        "provider": "THE_ODDS_API",
        "sport": "mlb",
        "capture_id": payload.get("capture_id"),
        "manifest_sha256": expected_manifest_sha,
        "raw_response_identity": "EXACT_BYTES_SHA256",
        "raw_bytes_location": "PRIVATE_REPOSITORY_ONLY",
        "network_fallback": False,
        "verified_response_count": len(verified),
        "responses": verified,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
