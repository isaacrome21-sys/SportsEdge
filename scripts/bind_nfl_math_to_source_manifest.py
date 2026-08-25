#!/usr/bin/env python3
"""Bind schedule-derived NFL math evidence to the canonical source manifest.

The key-number target is calculated from the frozen schedule, while production
M2 evidence also depends on PBP, participation, depth charts and stadium data.
This step verifies that the manifest's schedule entry is the exact schedule that
produced the math artifact, then promotes the provenance identity from the
schedule hash to the full manifest hash.  It does not alter any math result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.sports.nfl.source_manifest import manifest_sha256


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--math-evidence", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    math_payload = json.loads(args.math_evidence.read_text(encoding="utf-8"))
    manifest_payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    manifest = {key: value for key, value in manifest_payload.items() if key not in {"manifest_sha256", "participation_attribution"}}
    computed_manifest_sha = manifest_sha256(manifest)
    recorded_manifest_sha = str(manifest_payload.get("manifest_sha256") or "").lower()
    if computed_manifest_sha != recorded_manifest_sha:
        raise SystemExit("NFL_SOURCE_MANIFEST_SELF_HASH_MISMATCH")

    artifact = math_payload.get("math_artifact", math_payload)
    schedule_hash = str(artifact.get("source_sha256") or "").lower()
    schedule_entry = next((row for row in manifest.get("sources", []) if row.get("name") == "schedule"), None)
    if schedule_entry is None:
        raise SystemExit("NFL_SOURCE_SCHEDULE_ENTRY_REQUIRED")
    if str(schedule_entry.get("sha256") or "").lower() != schedule_hash:
        raise SystemExit("NFL_MATH_SCHEDULE_MANIFEST_MISMATCH")

    bound_artifact = dict(artifact)
    bound_artifact["schedule_source_sha256"] = schedule_hash
    bound_artifact["source_sha256"] = computed_manifest_sha
    bound_artifact["source_manifest_sha256"] = computed_manifest_sha
    bound_artifact["provenance_binding"] = "SCHEDULE_MATH_BOUND_TO_CANONICAL_MULTI_SOURCE_MANIFEST"

    output = dict(math_payload) if "math_artifact" in math_payload else {}
    if output:
        output["math_artifact"] = bound_artifact
        output["source_manifest_sha256"] = computed_manifest_sha
    else:
        output = bound_artifact
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "schedule_source_sha256": schedule_hash,
        "source_manifest_sha256": computed_manifest_sha,
        "binding": bound_artifact["provenance_binding"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
