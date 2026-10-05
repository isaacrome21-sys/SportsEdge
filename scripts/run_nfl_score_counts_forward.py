#!/usr/bin/env python3
"""Materialize a frozen NFL_SCORE_COUNTS_G1 pregame prediction from bound bytes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.run_nfl_score_counts_attempt import code_identity, iter_projected_pbp, read_csv
from sportsedge.sports.nfl.score_counts_artifact import build_forward_prediction
from sportsedge.sports.nfl.score_counts_features import build_score_count_forward_rows
from sportsedge.sports.nfl.score_counts_forward_bundle import (
    ScoreCountForwardError,
    build_forward_bundle,
    verify_forward_receipts,
)


def run(
    *,
    fit_path: Path,
    receipts_path: Path,
    target_game_ids: list[str],
    prediction_at: str,
    output_path: Path,
) -> dict:
    fit = json.loads(fit_path.read_text(encoding="utf-8"))
    if fit.get("status") != "DEVELOPMENT_ATTEMPT_PASS":
        raise ScoreCountForwardError("PASSING_DEVELOPMENT_FIT_REQUIRED")
    gate = fit.get("development_gate")
    if not isinstance(gate, dict) or gate.get("pass") is not True:
        raise ScoreCountForwardError("PASSING_DEVELOPMENT_GATE_REQUIRED")

    receipts = json.loads(receipts_path.read_text(encoding="utf-8"))
    parser_sha = code_identity()
    if str(fit.get("code_identity") or "") != parser_sha:
        raise ScoreCountForwardError("FIT_CURRENT_CODE_IDENTITY_MISMATCH")
    manifest = verify_forward_receipts(
        receipts, prediction_at=prediction_at, parser_code_sha256=parser_sha
    )

    raw_sources = list(receipts["sources"])
    schedule_paths = [Path(str(x["path"])) for x in raw_sources if str(x["role"]).lower() == "schedule"]
    pbp_paths = [Path(str(x["path"])) for x in raw_sources if str(x["role"]).lower() == "pbp"]
    depth_paths = [Path(str(x["path"])) for x in raw_sources if str(x["role"]).lower() == "depth"]

    schedule_rows = read_csv(schedule_paths[0])
    depth_rows = []
    for path in depth_paths:
        depth_rows.extend(read_csv(path))

    forward_rows = build_score_count_forward_rows(
        schedule_rows=schedule_rows,
        pbp_rows=iter_projected_pbp(pbp_paths),
        depth_rows=depth_rows,
        target_game_ids=target_game_ids,
        as_of=prediction_at,
        seasons=tuple(range(2018, 2027)),
    )
    prediction = build_forward_prediction(
        fit,
        forward_rows,
        prediction_at=prediction_at,
        source_manifest_sha256=str(fit["source_manifest_sha256"]),
        code_identity=parser_sha,
        paths=50000,
    )
    bundle = build_forward_bundle(
        fit_artifact=fit,
        prediction=prediction,
        forward_manifest=manifest,
        forward_rows=forward_rows,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return {
        "status": bundle["status"],
        "game_count": len(prediction["games"]),
        "fit_artifact_sha256": bundle["fit_artifact_sha256"],
        "forward_source_manifest_sha256": bundle["forward_source_manifest_sha256"],
        "prediction_sha256": bundle["prediction_sha256"],
        "bundle_sha256": bundle["bundle_sha256"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit-artifact", type=Path, required=True)
    ap.add_argument("--source-receipts", type=Path, required=True)
    ap.add_argument("--target-game-id", action="append", required=True)
    ap.add_argument("--prediction-at", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    summary = run(
        fit_path=args.fit_artifact,
        receipts_path=args.source_receipts,
        target_game_ids=args.target_game_id,
        prediction_at=args.prediction_at,
        output_path=args.output,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
