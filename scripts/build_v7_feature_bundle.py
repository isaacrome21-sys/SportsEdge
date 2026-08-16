#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from sportsedge.v7_feature_bundle import build_v7_feature_payload


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"V7_SOURCE_BUNDLE_INVALID:{path}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic pregame V7 feature payloads from normalized source bundles.")
    parser.add_argument("--input", default="artifacts/v7-shadow-state/source_bundle.json")
    parser.add_argument("--output", default="artifacts/v7-shadow-state/current_features.json")
    args = parser.parse_args()

    source_path = Path(args.input)
    if not source_path.exists():
        raise SystemExit("V7_SOURCE_BUNDLE_MISSING")
    material = _load(source_path)
    if not isinstance(material, list):
        raise SystemExit("V7_SOURCE_BUNDLE_MUST_BE_LIST")

    rows: list[dict[str, Any]] = []
    required = {
        "game_pk", "market", "prediction_as_of", "starter_rows", "bullpen_rows",
        "statcast_rows", "platoon", "park", "weather", "travel",
    }
    for raw in material:
        if not isinstance(raw, Mapping):
            raise SystemExit("V7_SOURCE_ROW_MUST_BE_OBJECT")
        missing = sorted(required - set(raw))
        if missing:
            raise SystemExit(f"V7_SOURCE_ROW_MISSING:{','.join(missing)}")
        feature_payload = build_v7_feature_payload(
            as_of=raw["prediction_as_of"],
            starter_rows=raw["starter_rows"],
            bullpen_rows=raw["bullpen_rows"],
            statcast_rows=raw["statcast_rows"],
            platoon=raw["platoon"],
            park=raw["park"],
            weather=raw["weather"],
            travel=raw["travel"],
            umpire=raw.get("umpire"),
            catcher=raw.get("catcher"),
        )
        row = {
            "game_pk": int(raw["game_pk"]),
            "market": str(raw["market"]),
            "prediction_as_of": raw["prediction_as_of"],
            "feature_payload": feature_payload,
        }
        if raw.get("baseline_probability") is not None:
            row["baseline_probability"] = raw["baseline_probability"]
        rows.append(row)

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(rows, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"state": "BUILT", "rows": len(rows), "output": str(output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
