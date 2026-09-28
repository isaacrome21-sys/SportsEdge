#!/usr/bin/env python3
"""Materialize and verify the preregistered CFB altitude static snapshot.

No model fit/evaluation is performed and no challenger attempt is consumed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.request import Request, urlopen

from sportsedge.sports.cfb.altitude_prereg import POLICY_PATH, verify_altitude_snapshot
from sportsedge.sports.cfb.altitude_snapshot import (
    SOURCE_MIRROR_RAW_URL,
    materialize_snapshot,
    verify_frozen_binding,
)


DEFAULT_OUTPUT_DIR = Path("data/cfb/altitude")
DEFAULT_BINDING = Path("config/cfb_altitude_snapshot_binding_v1.json")
SNAPSHOT_NAME = "cfb_altitude_static_v1.jsonl"
MANIFEST_NAME = "cfb_altitude_static_v1.manifest.json"


def _fetch_source() -> bytes:
    request = Request(
        SOURCE_MIRROR_RAW_URL,
        headers={"User-Agent": "SportsEdge-CFB-altitude-snapshot/1.0"},
    )
    with urlopen(request, timeout=60) as response:  # noqa: S310 - immutable pinned HTTPS source
        return response.read()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument(
        "--source-file",
        type=Path,
        help="Optional local copy of the exact pinned source bytes; useful for offline reproducibility.",
    )
    parser.add_argument(
        "--retrieved-at-utc",
        help="Explicit ISO-8601 retrieval time. Defaults to the current UTC time.",
    )
    args = parser.parse_args()

    if args.source_file:
        source_bytes = args.source_file.read_bytes()
    else:
        source_bytes = _fetch_source()

    retrieved_at = args.retrieved_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    materialized = materialize_snapshot(source_bytes, retrieved_at_utc=retrieved_at)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = args.output_dir / SNAPSHOT_NAME
    manifest_path = args.output_dir / MANIFEST_NAME
    snapshot_path.write_bytes(materialized.snapshot_bytes)
    manifest_path.write_text(
        json.dumps(materialized.manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    policy = json.loads(Path(POLICY_PATH).read_text(encoding="utf-8"))
    policy_binding = verify_altitude_snapshot(
        policy=policy,
        manifest=materialized.manifest,
        snapshot_path=snapshot_path,
    )
    if policy_binding["status"] != "SNAPSHOT_BOUND_NO_EVALUATION":
        raise SystemExit(json.dumps(policy_binding, sort_keys=True))

    frozen_binding = json.loads(args.binding.read_text(encoding="utf-8"))
    frozen_result = verify_frozen_binding(
        manifest=materialized.manifest,
        binding=frozen_binding,
    )

    print(
        json.dumps(
            {
                "status": frozen_result["status"],
                "policy_status": policy_binding["status"],
                "snapshot": str(snapshot_path),
                "manifest": str(manifest_path),
                "binding": str(args.binding),
                "record_count": materialized.manifest["record_count"],
                "content_sha256": materialized.manifest["content_sha256"],
                "fit_performed": False,
                "evaluation_performed": False,
                "attempt_consumed": False,
                "attempts_used": 0,
                "attempts_max": 3,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
