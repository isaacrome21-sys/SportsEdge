#!/usr/bin/env python3
"""Build the pre-fit manifest for the preregistered CFB altitude challenger.

No candidate is fit, scored, ranked, or selected. The command only binds exact
baseline rows, game identity metadata, and the frozen altitude snapshot.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.altitude_dataset import (
    CFBAltitudeDatasetError,
    build_altitude_dataset_manifest,
)

DEFAULT_BINDING = ROOT / "config/cfb_altitude_snapshot_binding_v1.json"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CFBAltitudeDatasetError(
                f"ALTITUDE_DATASET_SNAPSHOT_JSON_INVALID:{line_no}"
            ) from exc
        if not isinstance(row, dict):
            raise CFBAltitudeDatasetError(
                f"ALTITUDE_DATASET_SNAPSHOT_ROW_INVALID:{line_no}"
            )
        rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-rows", type=Path, required=True)
    parser.add_argument("--game-metadata", type=Path, required=True)
    parser.add_argument("--snapshot-jsonl", type=Path, required=True)
    parser.add_argument("--snapshot-manifest", type=Path, required=True)
    parser.add_argument("--binding", type=Path, default=DEFAULT_BINDING)
    parser.add_argument("--manifest-out", type=Path, required=True)
    parser.add_argument("--private-enriched-out", type=Path)
    args = parser.parse_args(argv)

    try:
        baseline = _load_json(args.baseline_rows)
        metadata = _load_json(args.game_metadata)
        snapshot_manifest = _load_json(args.snapshot_manifest)
        binding = _load_json(args.binding)
        snapshot_records = _load_jsonl(args.snapshot_jsonl)
        if not isinstance(baseline, list) or not isinstance(metadata, list):
            raise CFBAltitudeDatasetError("ALTITUDE_DATASET_INPUT_LIST_REQUIRED")
        rows, manifest = build_altitude_dataset_manifest(
            baseline_rows=baseline,
            game_metadata_rows=metadata,
            snapshot_records=snapshot_records,
            snapshot_manifest=snapshot_manifest,
            frozen_snapshot_binding=binding,
        )
    except (OSError, json.JSONDecodeError, CFBAltitudeDatasetError) as exc:
        print(json.dumps({
            "status": "BLOCKED_ALTITUDE_DATASET_MANIFEST",
            "reason": str(exc),
            "fit_performed": False,
            "evaluation_performed": False,
            "attempt_consumed": False,
            "model_p_created": False,
            "promotion_authority": False,
            "official_authority": False,
        }, sort_keys=True))
        return 2

    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.private_enriched_out is not None:
        args.private_enriched_out.parent.mkdir(parents=True, exist_ok=True)
        args.private_enriched_out.write_text(
            json.dumps(rows, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    print(json.dumps({
        "status": manifest["status"],
        "row_count": manifest["row_count"],
        "seasons": manifest["seasons"],
        "enriched_rows_sha256": manifest["enriched_rows_sha256"],
        "fit_performed": False,
        "evaluation_performed": False,
        "attempt_consumed": False,
        "attempts_used": 0,
        "attempts_max": 3,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
