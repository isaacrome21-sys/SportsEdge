#!/usr/bin/env python3
"""Run isolated NFL V2 candidate validation on exact production history inputs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.run_nfl_production_validation import (
    _DEPTH_FIELDS,
    _PARTICIPATION_FIELDS,
    _PBP_FIELDS,
    _STADIUM_FIELDS,
    _extend,
    _files,
    _read_projected,
    _sha,
    apply_pinned_starting_qb_overrides,
    audit_starting_qb_coverage,
    bridge_preopening_away_origins,
)
from sportsedge.sports.nfl.history import normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.m2_history_features import fit_nfl_prior_decay_curves
from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows
from sportsedge.sports.nfl.m2_v2_nested_validation import build_nfl_m2_v2_nested_candidate_evidence
from sportsedge.sports.nfl.m2_v2_validation import build_nfl_m2_v2_candidate_evidence
from sportsedge.sports.nfl.m2_v2b_validation import build_nfl_m2_v2b_candidate_evidence
from sportsedge.sports.nfl.m2_v2c_validation import build_nfl_m2_v2c_candidate_evidence
from sportsedge.sports.nfl.source_manifest import manifest_sha256

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _verified_manifest(payload: dict) -> tuple[str, dict[str, str]]:
    expected = str(payload.get("manifest_sha256") or "").strip().lower()
    if len(expected) != 64:
        raise SystemExit("NFL_M2_V2_SOURCE_MANIFEST_HASH_MISSING")
    core = {
        "schema_version": payload.get("schema_version"),
        "sport": payload.get("sport"),
        "schedule_anchor_sha256": payload.get("schedule_anchor_sha256"),
        "sources": payload.get("sources"),
    }
    if manifest_sha256(core) != expected:
        raise SystemExit("NFL_M2_V2_SOURCE_MANIFEST_HASH_MISMATCH")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise SystemExit("NFL_M2_V2_SOURCE_MANIFEST_ROWS_INVALID")
    by_name: dict[str, str] = {}
    for raw in sources:
        if not isinstance(raw, dict):
            raise SystemExit("NFL_M2_V2_SOURCE_MANIFEST_ROW_INVALID")
        name = str(raw.get("name") or "").strip()
        digest = str(raw.get("sha256") or "").strip().lower()
        if not name or len(digest) != 64 or name in by_name:
            raise SystemExit("NFL_M2_V2_SOURCE_MANIFEST_ROW_INVALID")
        by_name[name] = digest
    return expected, by_name


def _assert_source(path: Path, expected: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"NFL_M2_V2_SOURCE_FILE_MISSING:{label}")
    actual = _sha(path)
    if actual != expected:
        raise SystemExit(f"NFL_M2_V2_SOURCE_FILE_HASH_MISMATCH:{label}")


def _attach_run_provenance(
    evidence: dict,
    *,
    git_sha: str,
    args: argparse.Namespace,
    history_row_count: int,
    issue_count_before: int,
    override_count: int,
    stadium_bridge_count: int,
) -> dict:
    evidence.update({
        "code_git_sha": git_sha,
        "season_range": [args.start_season, args.end_season],
        "point_in_time_history_row_count": history_row_count,
        "neutral_site_policy": args.neutral_site_policy,
        "source_manifest_path": str(args.source_manifest),
        "starting_qb_coverage_issue_count_before_override": issue_count_before,
        "starting_qb_coverage_issue_count": 0,
        "starting_qb_override_count": override_count,
        "stadium_home_origin_bridge_count": stadium_bridge_count,
        "production_registry_consumes_this_artifact": False,
    })
    return evidence


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-file", type=Path, required=True)
    parser.add_argument("--pbp-dir", type=Path, required=True)
    parser.add_argument("--participation-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--stadium-file", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--starter-override-file", type=Path, default=Path("config/nfl_historical_starter_overrides.json"))
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--start-season", type=int, default=2016)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--min-train-seasons", type=int, default=2)
    parser.add_argument("--ridge-alpha", type=float, default=10.0)
    parser.add_argument("--kernel-scale", type=float, default=1.0)
    parser.add_argument("--neutral-site-policy", choices=("error", "exclude_from_evaluation"), default="exclude_from_evaluation")
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_m2_v2_candidate_validation.json"))
    parser.add_argument("--nested-out", type=Path, default=Path("artifacts/football/nfl_m2_v2_nested_candidate_validation.json"))
    parser.add_argument("--v2b-out", type=Path, default=Path("artifacts/football/nfl_m2_v2b_candidate_validation.json"))
    parser.add_argument("--v2c-out", type=Path, default=Path("artifacts/football/nfl_m2_v2c_candidate_validation.json"))
    args = parser.parse_args()

    git_sha = str(args.git_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("NFL_M2_V2_GIT_SHA_INVALID")
    if args.end_season < args.start_season or args.start_season < 2016:
        raise SystemExit("NFL_M2_V2_SEASON_RANGE_INVALID")

    try:
        manifest_payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NFL_M2_V2_SOURCE_MANIFEST_INVALID:{exc}") from exc
    manifest_hash, expected_sources = _verified_manifest(manifest_payload)

    pbp_files = _files(args.pbp_dir, "play_by_play_{season}.{ext}", args.start_season, args.end_season)
    participation_files = _files(args.participation_dir, "pbp_participation_{season}.{ext}", args.start_season, args.end_season)
    depth_files = _files(args.depth_dir, "depth_charts_{season}.{ext}", args.start_season, args.end_season)
    required = {
        "schedule": args.schedule_file,
        "stadiums": args.stadium_file,
        "starter_overrides": args.starter_override_file,
    }
    for season, path in zip(range(args.start_season, args.end_season + 1), pbp_files):
        required[f"pbp_{season}"] = path
    for season, path in zip(range(args.start_season, args.end_season + 1), participation_files):
        required[f"participation_{season}"] = path
    for season, path in zip(range(args.start_season, args.end_season + 1), depth_files):
        required[f"depth_{season}"] = path
    for name, path in required.items():
        expected = expected_sources.get(name)
        if expected is None:
            raise SystemExit(f"NFL_M2_V2_SOURCE_MANIFEST_ENTRY_MISSING:{name}")
        _assert_source(path, expected, name)

    schedule = normalize_nfl_rows(
        parse_schedule_csv(args.schedule_file.read_text(encoding="utf-8-sig")),
        range(args.start_season, args.end_season + 1),
    )
    pbp: list[dict[str, str]] = []
    participation: list[dict[str, str]] = []
    depth: list[dict[str, str]] = []
    _extend(pbp, pbp_files, _PBP_FIELDS)
    _extend(participation, participation_files, _PARTICIPATION_FIELDS)
    _extend(depth, depth_files, _DEPTH_FIELDS)
    raw_stadiums = _read_projected(args.stadium_file, _STADIUM_FIELDS)
    stadiums, stadium_bridges = bridge_preopening_away_origins(schedule, raw_stadiums)
    prior_curves = fit_nfl_prior_decay_curves(
        schedule, pbp, min_train_seasons=args.min_train_seasons, weeks=range(1, 7)
    )

    try:
        override_payload = json.loads(args.starter_override_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NFL_M2_V2_STARTER_OVERRIDE_INVALID:{exc}") from exc
    before = audit_starting_qb_coverage(schedule, depth, eligible_seasons=prior_curves)
    depth, applied = apply_pinned_starting_qb_overrides(schedule, depth, override_payload)
    after = audit_starting_qb_coverage(schedule, depth, eligible_seasons=prior_curves)
    if after:
        raise SystemExit(f"NFL_M2_V2_STARTING_QB_COVERAGE_GAPS:{len(after)}")

    history_rows = build_nfl_m2_history_rows(
        schedule,
        pbp,
        participation,
        depth,
        stadiums,
        prior_decay_curves=prior_curves,
        neutral_site_policy=args.neutral_site_policy,
    )
    if not history_rows:
        raise SystemExit("NFL_M2_V2_HISTORY_ROWS_EMPTY")

    common = {
        "git_sha": git_sha,
        "args": args,
        "history_row_count": len(history_rows),
        "issue_count_before": len(before),
        "override_count": len(applied),
        "stadium_bridge_count": len(stadium_bridges),
    }
    v2a = _attach_run_provenance(
        build_nfl_m2_v2_candidate_evidence(
            history_rows,
            source_manifest_sha256=manifest_hash,
            min_train_seasons=args.min_train_seasons,
            ridge_alpha=args.ridge_alpha,
            kernel_scale=args.kernel_scale,
        ),
        **common,
    )
    nested = _attach_run_provenance(
        build_nfl_m2_v2_nested_candidate_evidence(
            history_rows,
            source_manifest_sha256=manifest_hash,
            min_train_seasons=args.min_train_seasons,
            ridge_alpha=args.ridge_alpha,
        ),
        **common,
    )
    v2b = _attach_run_provenance(
        build_nfl_m2_v2b_candidate_evidence(
            history_rows,
            source_manifest_sha256=manifest_hash,
            min_train_seasons=args.min_train_seasons,
            ridge_alpha=args.ridge_alpha,
            kernel_scale=args.kernel_scale,
        ),
        **common,
    )
    v2c = _attach_run_provenance(
        build_nfl_m2_v2c_candidate_evidence(
            history_rows,
            source_manifest_sha256=manifest_hash,
            min_train_seasons=args.min_train_seasons,
            ridge_alpha=args.ridge_alpha,
        ),
        **common,
    )
    _write(args.out, v2a)
    _write(args.nested_out, nested)
    _write(args.v2b_out, v2b)
    _write(args.v2c_out, v2c)

    print(json.dumps({
        "status": "V2_CANDIDATE_DIAGNOSTICS_COMPLETE",
        "history_rows": len(history_rows),
        "production_registry_consumes_these_artifacts": False,
        "v2a": {
            "model_id": v2a["model_id"],
            "candidate_historical_evidence": v2a["candidate_historical_evidence"],
            "signed_key_probability": v2a["candidate_distribution_profile"]["signed_key_probability"],
        },
        "v2a_nested": {
            "model_id": nested["model_id"],
            "selection_contract": nested["selection_contract"],
            "candidate_historical_evidence": nested["candidate_historical_evidence"],
            "signed_key_probability": nested["candidate_distribution_profile"]["signed_key_probability"],
            "outer_fold_kernel_selection": nested["outer_fold_kernel_selection"],
        },
        "v2b": {
            "model_id": v2b["model_id"],
            "candidate_historical_evidence": v2b["candidate_historical_evidence"],
            "signed_key_probability": v2b["candidate_distribution_profile"]["signed_key_probability"],
        },
        "v2c": {
            "model_id": v2c["model_id"],
            "candidate_historical_evidence": v2c["candidate_historical_evidence"],
            "signed_key_probability": v2c["candidate_distribution_profile"]["signed_key_probability"],
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
