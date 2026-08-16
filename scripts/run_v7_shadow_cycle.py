#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.v7_candidate import load_candidate, score_candidate
from sportsedge.v7_shadow import normalize_shadow_row


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"V7_SHADOW_INPUT_INVALID:{path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Score immutable V7 shadow predictions from a frozen candidate artifact and pregame feature bundle.")
    parser.add_argument("--candidate", default="artifacts/v7-shadow-state/candidate.json")
    parser.add_argument("--features", default="artifacts/v7-shadow-state/current_features.json")
    parser.add_argument("--output", default="artifacts/v7-shadow-state/captures/v7_shadow_rows.json")
    parser.add_argument("--status", default="artifacts/v7-shadow-state/v7_shadow_status.json")
    parser.add_argument("--allow-blocked", action="store_true")
    args = parser.parse_args()

    candidate_path = Path(args.candidate)
    features_path = Path(args.features)
    output_path = Path(args.output)
    status_path = Path(args.status)
    status_path.parent.mkdir(parents=True, exist_ok=True)

    missing = [str(p) for p in (candidate_path, features_path) if not p.exists()]
    if missing:
        status = {"state": "BLOCKED", "reason": "V7_FROZEN_INPUT_MISSING", "missing": missing}
        status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n")
        if args.allow_blocked:
            print(json.dumps(status, sort_keys=True))
            return 0
        raise SystemExit("V7_FROZEN_INPUT_MISSING")

    candidate = load_candidate(_load_json(candidate_path))
    bundle = _load_json(features_path)
    if not isinstance(bundle, list):
        raise SystemExit("V7_FEATURE_BUNDLE_MUST_BE_LIST")

    rows: list[dict[str, Any]] = []
    for item in bundle:
        if not isinstance(item, Mapping):
            raise SystemExit("V7_FEATURE_ROW_MUST_BE_OBJECT")
        required = {"game_pk", "market", "prediction_as_of", "feature_payload"}
        missing_fields = sorted(required - set(item))
        if missing_fields:
            raise SystemExit(f"V7_FEATURE_ROW_MISSING:{','.join(missing_fields)}")
        feature_payload = item["feature_payload"]
        if not isinstance(feature_payload, Mapping):
            raise SystemExit("V7_FEATURE_PAYLOAD_MUST_BE_OBJECT")
        probability = score_candidate(candidate, feature_payload)
        row = {
            "game_pk": int(item["game_pk"]),
            "market": str(item["market"]),
            "prediction_as_of": item["prediction_as_of"],
            "candidate_probability": probability,
            "candidate_sha256": candidate.candidate_sha256,
            "feature_contract_sha256": candidate.feature_contract_sha256,
            "sportsbook_data_used": False,
        }
        if item.get("baseline_probability") is not None:
            row["baseline_probability"] = item["baseline_probability"]
        rows.append(normalize_shadow_row(row))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
    status = {
        "state": "CAPTURED",
        "rows": len(rows),
        "candidate_sha256": candidate.candidate_sha256,
        "feature_contract_sha256": candidate.feature_contract_sha256,
        "sportsbook_data_used": False,
    }
    status_path.write_text(json.dumps(status, sort_keys=True, indent=2) + "\n")
    print(json.dumps(status, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
