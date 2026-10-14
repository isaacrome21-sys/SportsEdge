#!/usr/bin/env python3
"""Build the CFB four-family evaluation data snapshots + dry-run manifest.

RESEARCH ONLY — machinery, not execution. This CLI verifies every
pinned source by hash, builds the three content-addressed snapshots
(results / CFBD descriptive lines / team directory) through the pure
bindings module (``sportsedge/research/cfb_four_family_bindings_v1.py``),
round-trips them through the bindings loaders, and emits a DRY-RUN
manifest (run state NOT_RUN, zero probabilities computed, no attempt
consumed). It never calls the harness scoring path and never
constructs a probability for a real game.

Sources are read from a staging directory:

    <sources-dir>/schedules/cfb_schedule_<season>.csv.gz   (2013-2025)
    <sources-dir>/cfb_line_odds.csv.gz                     (pinned archive)
    <sources-dir>/cfb_team_info_2024.parquet               (pinned table)

Every file is verified against the pins in
``config/research/cfb_four_family_bindings_v1.json`` before use; any
mismatch aborts the build. The team table is parquet: pyarrow must be
importable (set PYTHONPATH to an install that provides it).

Usage:
    python3 scripts/build_cfb_eval_snapshots.py \
        --sources-dir <dir> --out-dir <dir> [--repo-root <dir>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge.research import cfb_four_family_bindings_v1 as bindings  # noqa: E402


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def refuse(message: str) -> None:
    print("BUILD REFUSED: " + message, file=sys.stderr)
    raise SystemExit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument(
        "--config",
        default=str(REPO_ROOT / "config/research/cfb_four_family_bindings_v1.json"),
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    args = parser.parse_args()

    sources = Path(args.sources_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repo_root = Path(args.repo_root)
    bindings_cfg = json.loads(Path(args.config).read_text(encoding="utf-8"))
    verification: list[dict] = []

    # ---- schedules: verify every season file against its pin --------
    schedule_cfg = bindings_cfg["sources"]["schedules"]
    season_files: dict[int, bytes] = {}
    source_records = {
        "repository": schedule_cfg["repository"],
        "release_tag": schedule_cfg["release_tag"],
        "release_id": schedule_cfg["release_id"],
        "contract": schedule_cfg["contract"],
        "data_branch": schedule_cfg["data_branch"],
        "data_branch_commit": schedule_cfg["data_branch_commit"],
        "files": {},
    }
    for season_text, pin in sorted(schedule_cfg["seasons"].items()):
        season = int(season_text)
        path = sources / "schedules" / pin["asset_name"]
        if not path.exists():
            refuse("missing schedule file %s" % (path,))
        data = path.read_bytes()
        digest = sha256(data)
        ok = digest == pin["sha256"] and len(data) == pin["size_bytes"]
        verification.append(
            {
                "source": "schedule:%s" % season,
                "sha256": digest,
                "size_bytes": len(data),
                "pin_source": pin["pin_source"],
                "verified": ok,
            }
        )
        if not ok:
            refuse(
                "schedule pin mismatch season %s (sha256 %s, size %d)"
                % (season, digest, len(data))
            )
        season_files[season] = data
        source_records["files"][season_text] = {
            "asset_name": pin["asset_name"],
            "sha256": digest,
            "size_bytes": len(data),
            "pin_source": pin["pin_source"],
        }

    # ---- team directory table ----------------------------------------
    directory_cfg = bindings_cfg["sources"]["team_directory"]["identity_table"]
    table_path = sources / Path(directory_cfg["path"]).name
    if not table_path.exists():
        refuse("missing team directory table %s" % (table_path,))
    table_bytes = table_path.read_bytes()
    digest = sha256(table_bytes)
    blob = git_blob_sha1(table_bytes)
    ok = (
        digest == directory_cfg["sha256"]
        and blob == directory_cfg["git_blob_sha1"]
        and len(table_bytes) == directory_cfg["size_bytes"]
    )
    verification.append(
        {
            "source": "team_directory_table",
            "sha256": digest,
            "git_blob_sha1": blob,
            "size_bytes": len(table_bytes),
            "verified": ok,
        }
    )
    if not ok:
        refuse("team directory table pin mismatch")
    try:
        import pyarrow.parquet as pq
    except ImportError:
        refuse(
            "pyarrow is required to parse the pinned team directory "
            "parquet; install it and set PYTHONPATH"
        )
    table_file = out_dir / "_team_info_stage.parquet"
    table_file.write_bytes(table_bytes)
    try:
        rows = pq.read_table(str(table_file)).to_pylist()
    finally:
        table_file.unlink(missing_ok=True)
    team_rows = [
        {
            "team_id": row["team_id"],
            "school": row["school"],
            "abbreviation": row["abbreviation"],
            "conference": row["conference"],
            "classification": row["classification"],
        }
        for row in rows
    ]
    overrides = bindings_cfg["fbs_membership_overrides"]
    directory_snapshot = bindings.build_directory_snapshot(
        team_rows,
        provenance={
            "repository": directory_cfg["repository"],
            "commit": directory_cfg["commit"],
            "path": directory_cfg["path"],
            "git_blob_sha1": blob,
            "sha256": digest,
            "finding": directory_cfg["finding"],
        },
        overrides=overrides,
    )
    directory = bindings.DirectorySnapshot(directory_snapshot)

    # ---- results snapshot ---------------------------------------------
    results_snapshot = bindings.build_results_snapshot(
        season_files, directory, source_records=source_records
    )

    # ---- lines archive: verify the CFB_HISTORICAL_MARKET_SOURCE pin --
    lines_cfg = bindings_cfg["sources"]["lines"]
    lines_path = sources / "cfb_line_odds.csv.gz"
    if not lines_path.exists():
        refuse("missing lines archive %s" % (lines_path,))
    lines_bytes = lines_path.read_bytes()
    digest = sha256(lines_bytes)
    blob = git_blob_sha1(lines_bytes)
    ok = (
        digest == lines_cfg["expected_sha256"]
        and blob == lines_cfg["expected_git_blob_sha1"]
        and len(lines_bytes) == lines_cfg["expected_size_bytes"]
    )
    verification.append(
        {
            "source": "lines_archive",
            "sha256": digest,
            "git_blob_sha1": blob,
            "size_bytes": len(lines_bytes),
            "verified": ok,
        }
    )
    if not ok:
        refuse("lines archive pin mismatch vs CFB_HISTORICAL_MARKET_SOURCE_V1")
    lines_snapshot = bindings.build_lines_snapshot(
        lines_bytes,
        designated_provider=lines_cfg["designated_provider"],
        seasons=lines_cfg["snapshot_seasons"],
        source_record={
            "source_id": lines_cfg["source_id"],
            "upstream_repository": lines_cfg["upstream_repository"],
            "upstream_commit": lines_cfg["upstream_commit"],
            "upstream_path": lines_cfg["upstream_path"],
            "sha256": digest,
            "git_blob_sha1": blob,
            "restrictions_version": lines_cfg["restrictions_version"],
            "limitations": lines_cfg["limitations"],
        },
    )

    # ---- write snapshots (canonical bytes; ids are content hashes) ---
    written: dict[str, dict] = {}
    for name, snapshot in (
        ("results_snapshot", results_snapshot),
        ("lines_snapshot", lines_snapshot),
        ("directory_snapshot", directory_snapshot),
    ):
        data = canonical(snapshot)
        path = out_dir / (name + ".json")
        path.write_bytes(data)
        written[name] = {
            "path": path.name,
            "snapshot_id": snapshot["snapshot_id"],
            "file_sha256": sha256(data),
            "file_bytes": len(data),
        }

    # ---- round-trip through the bindings loaders ----------------------
    results_payload, games = bindings.load_results_snapshot(
        (out_dir / "results_snapshot.json").read_bytes()
    )
    results_index = {
        record["game_id"]: record for record in results_payload["games"]
    }
    lines_load = bindings.load_lines_snapshot(
        (out_dir / "lines_snapshot.json").read_bytes(),
        results_index=results_index,
    )
    directory_rt = bindings.DirectorySnapshot(
        json.loads((out_dir / "directory_snapshot.json").read_bytes())
    )
    if directory_rt.snapshot_id != directory.snapshot_id:
        refuse("directory snapshot round-trip id mismatch")

    # ---- engine identity + dry-run manifest (NOT_RUN; no producer) ---
    engine_files = {
        rel: (repo_root / rel).read_bytes() for rel in bindings.ENGINE_FILES
    }
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    identity = bindings.EngineIdentity.from_file_bytes(
        engine_files, source_commit=source_commit
    )
    # Bind the producer on synthetic self-check inputs only: bind()
    # proves neutrality discipline; no real game is ever passed to it.
    from sportsedge.research.cfb_four_family_evaluation_v1 import EvalConfig

    producer = bindings.FrozenEngineProducer.bind(
        identity=identity, config=EvalConfig()
    )
    dry_run = bindings.build_dry_run_manifest(
        bindings_cfg=bindings_cfg,
        results_snapshot_id=results_snapshot["snapshot_id"],
        lines_snapshot_id=lines_snapshot["snapshot_id"],
        games=games,
        lines_load=lines_load,
        directory=directory_rt,
        engine_fragment=producer.run_manifest_fragment(),
    )
    dry_run_path = out_dir / "DRY_RUN_MANIFEST.json"
    dry_run_path.write_bytes(canonical(dry_run))

    snapshot_manifest = {
        "manifest": "CFB_FOUR_FAMILY_SNAPSHOT_MANIFEST_V1",
        "run_state": "NOT_RUN",
        "source_verification": verification,
        "snapshots": written,
        "dry_run_manifest": {
            "path": dry_run_path.name,
            "file_sha256": sha256(dry_run_path.read_bytes()),
        },
        "results": {
            "games": results_payload["game_count"],
            "per_season": results_payload["per_season"],
            "unresolved_team_ids": results_payload["unresolved_team_ids"],
        },
        "lines": {
            "games": lines_snapshot["payload"]["game_count"],
            "quarantine_records": len(lines_snapshot["payload"]["quarantine"]),
            "load_flags": lines_load.flags,
        },
    }
    (out_dir / "SNAPSHOT_MANIFEST.json").write_bytes(canonical(snapshot_manifest))
    print(json.dumps(snapshot_manifest, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
