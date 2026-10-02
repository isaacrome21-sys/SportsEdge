#!/usr/bin/env python3
"""Spend the single frozen 2025 NFL prop-usage V1 validation look."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import sys
import tempfile
from urllib.request import Request, urlopen

import pandas as pd
import pyreadr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fit_nfl_prop_usage_v1 import _build_attempt9_runtime
from sportsedge.research.nfl_prop_usage_v1_validate_2025 import (
    FIT_RAW_SHA,
    INACTIVE_AUDIT_SHA,
    SOURCE_AUDIT_SHA,
    build_attempt9_team_environment_2025,
    load_lock,
    raw_sha256,
    validate_2025,
    validate_bound_artifacts,
)

UA = "SportsEdge-NFL-prop-usage-v1-2025-one-look/1.0"


def fetch(url: str, *, timeout: int = 120) -> tuple[bytes, dict[str, object]]:
    req = Request(url, headers={"User-Agent": UA})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        raise RuntimeError(f"PROP_V1_2025_SOURCE_EMPTY:{url}")
    return raw, {
        "url": url,
        "bytes": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def csv_rows(raw: bytes) -> list[dict[str, str]]:
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    if not rows:
        raise RuntimeError("PROP_V1_2025_CSV_EMPTY")
    return rows


def read_depth(raw: bytes, temp_dir: Path) -> list[dict[str, object]]:
    path = temp_dir / "depth_charts_2025.rds"
    path.write_bytes(raw)
    parsed = pyreadr.read_r(str(path))
    if not parsed:
        raise RuntimeError("PROP_V1_2025_DEPTH_RDS_EMPTY")
    frame = next(iter(parsed.values()))
    return frame.to_dict(orient="records")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def run(
    *,
    fit_path: Path,
    source_audit_path: Path,
    inactive_audit_path: Path,
    out_path: Path,
    summary_path: Path,
    spend_path: Path,
) -> dict[str, object]:
    lock = load_lock()

    fit_raw = fit_path.read_bytes()
    source_raw = source_audit_path.read_bytes()
    inactive_raw = inactive_audit_path.read_bytes()
    fit = json.loads(fit_raw)
    source_audit, inactive_audit = validate_bound_artifacts(
        fit_artifact=fit,
        fit_raw=fit_raw,
        source_audit_raw=source_raw,
        inactive_audit_raw=inactive_raw,
    )

    receipts = source_audit["receipts"]
    raw_sources: dict[str, bytes] = {}
    validation_receipts: dict[str, object] = {}

    # Re-fetch and hash every non-outcome source before the one-look is spent.
    for label in ("props_rows", "props_rows_extra", "depth_charts"):
        expected = receipts[label]
        raw, receipt = fetch(str(expected["url"]))
        if receipt["sha256"] != expected["sha256"]:
            raise RuntimeError(
                f"PROP_V1_2025_SOURCE_SHA_MISMATCH:{label}:"
                f"{receipt['sha256']}:{expected['sha256']}"
            )
        raw_sources[label] = raw
        validation_receipts[label] = receipt

    # The spend receipt is durable evidence that any access below consumes 2025,
    # even if parsing or scoring later fails.
    spend = {
        "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_2025_SPEND_RECEIPT",
        "status": "VALIDATION_WINDOW_SPENT_BEFORE_TARGET_SOURCE_ACCESS",
        "spent_at": datetime.now(timezone.utc).isoformat(),
        "fit_artifact_sha256": fit["artifact_sha256"],
        "fit_json_raw_sha256": raw_sha256(fit_raw),
        "source_audit_raw_sha256": raw_sha256(source_raw),
        "inactive_audit_raw_sha256": raw_sha256(inactive_raw),
        "target_sources_about_to_open": [
            lock["validation_inputs"]["games_uri"],
            lock["validation_inputs"]["player_stats_2025_uri"],
        ],
        "second_look_allowed": False,
    }
    write_json(spend_path, spend)

    try:
        games_raw, games_receipt = fetch(lock["validation_inputs"]["games_uri"])
        stats_raw, stats_receipt = fetch(
            lock["validation_inputs"]["player_stats_2025_uri"]
        )
        validation_receipts["games"] = games_receipt
        validation_receipts["player_stats_2025"] = stats_receipt

        props_frames = [
            pd.read_parquet(io.BytesIO(raw_sources["props_rows"])),
            pd.read_parquet(io.BytesIO(raw_sources["props_rows_extra"])),
        ]
        prop_rows = pd.concat(props_frames, ignore_index=True, sort=False).to_dict(
            orient="records"
        )

        with tempfile.TemporaryDirectory(prefix="sportsedge-prop-v1-2025-") as tmp:
            temp_dir = Path(tmp)
            depth_rows = read_depth(raw_sources["depth_charts"], temp_dir)
            runtime = _build_attempt9_runtime(temp_dir)

        games = csv_rows(games_raw)
        player_rows = csv_rows(stats_raw)
        env = build_attempt9_team_environment_2025(games, runtime)
        if not env:
            raise RuntimeError("PROP_V1_2025_ATTEMPT9_ENVIRONMENT_EMPTY")

        result = validate_2025(
            fit_artifact=fit,
            inactive_audit=inactive_audit,
            prop_rows=prop_rows,
            depth_rows=depth_rows,
            player_rows=player_rows,
            team_environment=env,
            source_receipts=validation_receipts,
        )
        write_json(out_path, result)

        summary = {
            "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_2025_VALIDATION_SUMMARY",
            "status": result["status"],
            "validation_window_spent": True,
            "artifact_sha256": result["artifact_sha256"],
            "n_rows": result["n_rows"],
            "n_by_market": result["n_by_market"],
            "metrics": result["metrics"],
            "gates": result["gates"],
            "excluded_reason_counts": result["excluded_reason_counts"],
            "player_stats_2025_sha256": stats_receipt["sha256"],
            "games_sha256": games_receipt["sha256"],
            "post_result_policy": result["post_result_policy"],
            "authority": result["authority"],
        }
        write_json(summary_path, summary)
        print("NFL_PROP_USAGE_V1_2025_VALIDATION=" + json.dumps(summary, sort_keys=True))
        return summary
    except Exception as exc:
        failure = {
            "schema": "SPORTSEDGE_NFL_PROP_USAGE_V1_2025_VALIDATION_FAILURE",
            "status": "VALIDATION_WINDOW_SPENT_TECHNICAL_FAILURE",
            "validation_window_spent": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "retune_allowed": False,
            "second_look_allowed": False,
        }
        write_json(summary_path, failure)
        raise


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", required=True)
    ap.add_argument("--source-audit", required=True)
    ap.add_argument("--inactive-audit", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--summary-out", required=True)
    ap.add_argument("--spend-out", required=True)
    args = ap.parse_args()
    run(
        fit_path=Path(args.fit),
        source_audit_path=Path(args.source_audit),
        inactive_audit_path=Path(args.inactive_audit),
        out_path=Path(args.out),
        summary_path=Path(args.summary_out),
        spend_path=Path(args.spend_out),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
