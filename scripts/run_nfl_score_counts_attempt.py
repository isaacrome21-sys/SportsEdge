#!/usr/bin/env python3
"""Governed development-attempt runner for NFL_SCORE_COUNTS_G1.

This runner consumes one numbered historical development attempt only when
explicitly dispatched. It downloads only the frozen source bytes, verifies every
SHA-256 before parsing, projects PBP through the market-blind allowlist, builds
PIT-safe training rows, and emits a deterministic fit artifact. It never binds
sportsbook quotes, creates betting authority, or writes forward predictions.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sportsedge.sports.nfl.score_counts_artifact import build_attempt_fit_artifact
from sportsedge.sports.nfl.score_counts_features import build_score_count_training_rows
from sportsedge.sports.nfl.score_counts_source_manifest import (
    build_score_count_source_manifest,
    load_source_contract,
)
from sportsedge.sports.nfl.score_counts_source_projection import project_pbp_row

DEVELOPMENT_SEASONS = tuple(range(2018, 2026))
IDENTITY_PATHS = (
    "sportsedge/sports/nfl/score_counts_source_projection.py",
    "sportsedge/sports/nfl/score_counts_features.py",
    "sportsedge/sports/nfl/m2_history_features.py",
    "sportsedge/sports/nfl/score_counts_g1.py",
    "sportsedge/sports/nfl/score_counts_artifact.py",
    "sportsedge/sports/nfl/score_counts_source_manifest.py",
    "scripts/run_nfl_score_counts_attempt.py",
)
PREREG_ADDENDUM = Path("config/research/nfl_score_counts_g1_prereg_addendum_v2.json")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def code_identity(root: Path = Path(".")) -> str:
    entries = {}
    for rel in IDENTITY_PATHS:
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f"CODE_IDENTITY_PATH_MISSING:{rel}")
        entries[rel] = sha256_file(path)
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def download_exact(uri: str, target: Path, expected_sha256: str, retries: int = 4) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    last = None
    for attempt in range(retries):
        try:
            req = Request(uri, headers={"User-Agent": "SportsEdge-score-count-attempt/1"})
            with urlopen(req, timeout=120) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            got = sha256_file(tmp)
            if got != expected_sha256:
                raise ValueError(
                    f"SHA256_MISMATCH:{target.name}:expected={expected_sha256}:got={got}"
                )
            os.replace(tmp, target)
            return
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(2)
    raise RuntimeError(f"DOWNLOAD_FAILED:{uri}:{last}")


def read_csv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def iter_projected_pbp(paths: list[Path]):
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                yield project_pbp_row(row)


def acquire_sources(contract: dict, root: Path, parser_sha: str) -> tuple[list[dict], Path, list[Path], list[Path]]:
    retrieved = datetime.now(timezone.utc).isoformat()
    receipts: list[dict] = []

    schedule_spec = contract["schedule"]
    schedule_path = root / "games.csv"
    download_exact(schedule_spec["fetch_uri"], schedule_path, schedule_spec["expected_sha256"])
    receipts.append({
        "name": "schedule",
        "fetch_uri": schedule_spec["fetch_uri"],
        "origin_uri": schedule_spec["fetch_uri"],
        "retrieved_at_utc": retrieved,
        "season_scope": list(DEVELOPMENT_SEASONS),
        "byte_sha256": sha256_file(schedule_path),
        "parser_code_sha256": parser_sha,
    })

    pbp_paths: list[Path] = []
    depth_paths: list[Path] = []
    for season in DEVELOPMENT_SEASONS:
        for family, ext, bucket in (
            ("pbp", ".csv.gz", pbp_paths),
            ("depth", ".csv", depth_paths),
        ):
            spec = contract[family][str(season)]
            path = root / family / f"{family}_{season}{ext}"
            download_exact(spec["fetch_uri"], path, spec["expected_sha256"])
            bucket.append(path)
            receipts.append({
                "name": f"{family}_{season}",
                "fetch_uri": spec["fetch_uri"],
                "origin_uri": spec["origin_uri"],
                "retrieved_at_utc": retrieved,
                "season_scope": [season],
                "byte_sha256": sha256_file(path),
                "parser_code_sha256": parser_sha,
            })
    return receipts, schedule_path, pbp_paths, depth_paths


def run_attempt(*, attempt_number: int, confirm: str, output_dir: Path) -> dict:
    expected_confirm = f"CONSUME_SCORE_COUNTS_ATTEMPT_{attempt_number}"
    if confirm != expected_confirm:
        raise RuntimeError(f"ATTEMPT_CONFIRMATION_REQUIRED:{expected_confirm}")
    if attempt_number not in {1, 2, 3}:
        raise RuntimeError("ATTEMPT_NUMBER_OUT_OF_FROZEN_BUDGET")

    output_dir.mkdir(parents=True, exist_ok=True)
    source_root = output_dir / "sources"
    parser_sha = code_identity()
    contract = load_source_contract()

    receipts, schedule_path, pbp_paths, depth_paths = acquire_sources(
        contract, source_root, parser_sha
    )
    manifest = build_score_count_source_manifest(
        receipts,
        parser_code_sha256=parser_sha,
        contract=contract,
        seasons=DEVELOPMENT_SEASONS,
    )
    (output_dir / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    schedule_rows = read_csv(schedule_path)
    depth_rows: list[dict[str, str]] = []
    for path in depth_paths:
        depth_rows.extend(read_csv(path))

    training_rows = build_score_count_training_rows(
        schedule_rows=schedule_rows,
        pbp_rows=iter_projected_pbp(pbp_paths),
        depth_rows=depth_rows,
        seasons=DEVELOPMENT_SEASONS,
    )
    if not training_rows:
        raise RuntimeError("NFL_SCORE_COUNTS_TRAINING_ROWS_EMPTY")

    prereg_sha = sha256_file(PREREG_ADDENDUM)
    artifact = build_attempt_fit_artifact(
        training_rows,
        attempt_number=attempt_number,
        source_manifest_sha256=manifest["manifest_sha256"],
        code_identity=parser_sha,
        prereg_addendum_sha256=prereg_sha,
    )
    artifact["runner"] = {
        "confirmation": expected_confirm,
        "code_identity": parser_sha,
        "training_row_count": len(training_rows),
        "market_projection_applied": True,
        "attempt_consumed": True,
        "authority": {
            "research_only": True,
            "creates_model_p": False,
            "pricing": False,
            "promotion": False,
            "staking": False,
            "official": False,
        },
    }
    # Adding runner metadata changes the top-level artifact payload, so refresh
    # the self-digest using the same canonical rule as the artifact module.
    artifact.pop("artifact_sha256", None)
    canonical = json.dumps(
        artifact, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    artifact["artifact_sha256"] = hashlib.sha256(canonical).hexdigest()

    out = output_dir / f"attempt_{attempt_number}_fit.json"
    out.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_ATTEMPT_RUN_SUMMARY_V1",
        "attempt_number": attempt_number,
        "status": artifact["status"],
        "artifact_sha256": artifact["artifact_sha256"],
        "source_manifest_sha256": manifest["manifest_sha256"],
        "code_identity": parser_sha,
        "training_row_count": len(training_rows),
        "development_gate_pass": bool(artifact["development_gate"]["pass"]),
        "attempt_consumed": True,
        "market_data_used": False,
        "authority": artifact["authority"],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--attempt-number", type=int, required=True)
    ap.add_argument("--confirm", required=True)
    ap.add_argument("--output-dir", type=Path)
    args = ap.parse_args()
    out = args.output_dir or Path(
        f"artifacts/football/score_counts/attempt_{args.attempt_number}"
    )
    summary = run_attempt(
        attempt_number=args.attempt_number,
        confirm=args.confirm,
        output_dir=out,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
