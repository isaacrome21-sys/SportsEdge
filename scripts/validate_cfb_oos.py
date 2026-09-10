#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.oos_validation import walk_forward_validate_cfb  # noqa: E402
from sportsedge.sports.cfb.source_manifest import (  # noqa: E402
    CFBSourceManifestError,
    validate_cfb_pit_source_manifest,
    verify_cfb_source_snapshots,
)
from sportsedge.sports.cfb.training_artifact import (  # noqa: E402
    CFBTrainingArtifactError,
    validate_cfb_pit_training_bundle,
)


def _load_json(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"CFB_OOS_JSON_MAPPING_REQUIRED:{path}")
    return payload, raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--training-bundle", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-evidence-root", type=Path, required=True)
    parser.add_argument("--fit-max-season", type=int, required=True)
    parser.add_argument("--min-train-rows", type=int, default=20)
    parser.add_argument("--ridge-alpha", type=float, default=10.0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        bundle, bundle_raw = _load_json(args.training_bundle)
        manifest, manifest_raw = _load_json(args.source_manifest)
        validated_bundle = validate_cfb_pit_training_bundle(
            bundle, raw_bytes=bundle_raw, fit_max_season=args.fit_max_season
        )
        validated_manifest = validate_cfb_pit_source_manifest(
            manifest, raw_bytes=manifest_raw, fit_max_season=args.fit_max_season
        )
        if validated_manifest["manifest_sha256"] != validated_bundle["source_manifest_sha256"]:
            raise ValueError("CFB_OOS_SOURCE_MANIFEST_SHA256_MISMATCH")
        source_verification = verify_cfb_source_snapshots(
            validated_manifest, evidence_root=args.source_evidence_root
        )
        report = walk_forward_validate_cfb(
            validated_bundle["rows"],
            min_train_rows=args.min_train_rows,
            ridge_alpha=args.ridge_alpha,
        ).to_dict()
        payload = {
            "schema_version": "CFB_BOUND_OOS_REPORT_V1",
            "status": "RESEARCH_ONLY_NOT_PROMOTION_EVIDENCE",
            "training_bundle_sha256": sha256(bundle_raw).hexdigest(),
            "source_manifest_sha256": validated_manifest["manifest_sha256"],
            "source_content_root_sha256": source_verification["source_content_root_sha256"],
            "source_snapshot_verified": True,
            "verified_source_count": source_verification["verified_source_count"],
            "fit_max_season": validated_bundle["fit_max_season"],
            "train_seasons": validated_bundle["train_seasons"],
            "row_count": validated_bundle["row_count"],
            "oos": report,
            "governance": {
                "promotion_changed": False,
                "truth_gate_changed": False,
                "eligible_changed": False,
                "model_p_created": False,
                "market_prices_used": False,
                "clv_evidence": False,
                "roi_evidence": False,
                "calibration_evidence": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": payload["status"], "output": str(args.output)}, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, ValueError, CFBTrainingArtifactError, CFBSourceManifestError) as exc:
        blocked = {
            "schema_version": "CFB_BOUND_OOS_REPORT_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "governance": {
                "promotion_changed": False,
                "truth_gate_changed": False,
                "eligible_changed": False,
                "model_p_created": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(blocked, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(blocked, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
