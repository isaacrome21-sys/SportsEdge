#!/usr/bin/env python3
from __future__ import annotations

"""Run NFL_LOCATION_SYMMETRIC_RIDGE_G1 on the exact frozen production-M2 history bytes.

This is a reused-history research readout only. It does not create Model_P,
promotion, staking, OFFICIAL, or bettor-facing release authority.
"""

import argparse
import json
from pathlib import Path
import re

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
from sportsedge.sports.nfl.location_symmetric_g1_validation import (
    validate_nfl_location_symmetric_g1,
)
from sportsedge.sports.nfl.m2_history_features import fit_nfl_prior_decay_curves
from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows
from sportsedge.sports.nfl.source_manifest import build_nfl_source_manifest, manifest_sha256

_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")


def build_history_and_manifest(args):
    schedule_sha = _sha(args.schedule_file)
    pbp_files = _files(args.pbp_dir, "play_by_play_{season}.{ext}", args.start_season, args.end_season)
    participation_files = _files(
        args.participation_dir,
        "pbp_participation_{season}.{ext}",
        args.start_season,
        args.end_season,
    )
    depth_files = _files(args.depth_dir, "depth_charts_{season}.{ext}", args.start_season, args.end_season)

    sources = [
        {"name": "schedule", "uri": "frozen://nflverse/games.csv", "sha256": schedule_sha},
        {"name": "stadiums", "uri": "frozen://greerreNFL/Stadiums/team_stadiums.csv", "sha256": _sha(args.stadium_file)},
        {
            "name": "starter_overrides",
            "uri": f"frozen://sportsedge/{args.starter_override_file.name}",
            "sha256": _sha(args.starter_override_file),
        },
    ]
    for prefix, paths in (
        ("pbp", pbp_files),
        ("participation", participation_files),
        ("depth", depth_files),
    ):
        for path in paths:
            season = next(
                token
                for token in path.stem.replace(".csv", "").split("_")
                if token.isdigit() and len(token) == 4
            )
            sources.append(
                {
                    "name": f"{prefix}_{season}",
                    "uri": f"frozen://nflverse/{path.name}",
                    "sha256": _sha(path),
                }
            )
    manifest = build_nfl_source_manifest(sources, schedule_anchor_sha256=schedule_sha)
    manifest_hash = manifest_sha256(manifest)

    schedule = normalize_nfl_rows(
        parse_schedule_csv(args.schedule_file.read_text(encoding="utf-8-sig")),
        range(args.start_season, args.end_season + 1),
    )
    pbp = []
    participation = []
    depth = []
    _extend(pbp, pbp_files, _PBP_FIELDS)
    _extend(participation, participation_files, _PARTICIPATION_FIELDS)
    _extend(depth, depth_files, _DEPTH_FIELDS)
    raw_stadiums = _read_projected(args.stadium_file, _STADIUM_FIELDS)
    stadiums, preopening_bridges = bridge_preopening_away_origins(schedule, raw_stadiums)

    prior_curves = fit_nfl_prior_decay_curves(
        schedule,
        pbp,
        min_train_seasons=args.min_train_seasons,
        weeks=range(1, 7),
    )
    before = audit_starting_qb_coverage(
        schedule,
        depth,
        eligible_seasons=prior_curves,
    )
    override_payload = json.loads(args.starter_override_file.read_text(encoding="utf-8"))
    depth, starter_overrides = apply_pinned_starting_qb_overrides(
        schedule,
        depth,
        override_payload,
    )
    after = audit_starting_qb_coverage(
        schedule,
        depth,
        eligible_seasons=prior_curves,
    )
    if after:
        compact = ";".join(
            f"{row['game_id']}:{row['side']}:{row['error']}" for row in after
        )
        raise SystemExit(f"NFL_G1_STARTING_QB_COVERAGE_GAPS:{len(after)}:{compact}")

    exclusions = {}
    history_rows = build_nfl_m2_history_rows(
        schedule,
        pbp,
        participation,
        depth,
        stadiums,
        prior_decay_curves=prior_curves,
        neutral_site_policy="exclude_from_evaluation",
        exclusion_report=exclusions,
    )
    if not history_rows:
        raise SystemExit("NFL_G1_HISTORY_ROWS_EMPTY")

    return {
        "history_rows": history_rows,
        "manifest": manifest,
        "manifest_sha256": manifest_hash,
        "schedule_sha256": schedule_sha,
        "preopening_stadium_bridges": preopening_bridges,
        "starting_qb_gaps_before_override": before,
        "starter_overrides": starter_overrides,
        "environment_exclusions": exclusions,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--schedule-file", type=Path, required=True)
    ap.add_argument("--pbp-dir", type=Path, required=True)
    ap.add_argument("--participation-dir", type=Path, required=True)
    ap.add_argument("--depth-dir", type=Path, required=True)
    ap.add_argument("--stadium-file", type=Path, required=True)
    ap.add_argument("--starter-override-file", type=Path, required=True)
    ap.add_argument("--git-sha", required=True)
    ap.add_argument("--start-season", type=int, default=2016)
    ap.add_argument("--end-season", type=int, default=2025)
    ap.add_argument("--min-train-seasons", type=int, default=2)
    ap.add_argument(
        "--execution-contract",
        type=Path,
        default=Path("config/research/nfl_location_symmetric_g1_readout_execution_v1.json"),
    )
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/football/nfl_location_symmetric_g1_readout.json"),
    )
    args = ap.parse_args()

    git_sha = str(args.git_sha).strip().lower()
    if not _GIT_SHA.fullmatch(git_sha):
        raise SystemExit("NFL_G1_READOUT_GIT_SHA_INVALID")
    execution = json.loads(args.execution_contract.read_text(encoding="utf-8"))
    if execution.get("schema") != "NFL_LOCATION_SYMMETRIC_G1_READOUT_EXECUTION_V1":
        raise SystemExit("NFL_G1_READOUT_EXECUTION_SCHEMA_INVALID")
    if execution.get("status") != "FROZEN_BEFORE_FIRST_REAL_READOUT":
        raise SystemExit("NFL_G1_READOUT_EXECUTION_NOT_FROZEN")
    if execution.get("pull_request_real_readout_forbidden") is not True:
        raise SystemExit("NFL_G1_READOUT_PR_GUARD_MISSING")
    if any(
        bool((execution.get("authority") or {}).get(key))
        for key in (
            "model_p",
            "truth_gate",
            "promotion",
            "staking",
            "official",
            "bettor_facing_release",
        )
    ):
        raise SystemExit("NFL_G1_READOUT_AUTHORITY_ESCALATION")

    built = build_history_and_manifest(args)
    report = validate_nfl_location_symmetric_g1(built["history_rows"])
    payload = {
        "schema": "NFL_LOCATION_SYMMETRIC_G1_REAL_READOUT_V1",
        "candidate_family": report["candidate_family"],
        "model_id": report["model_id"],
        "code_git_sha": git_sha,
        "execution_contract": execution["schema"],
        "source_contract": execution["source_contract"],
        "source_manifest_sha256": built["manifest_sha256"],
        "schedule_sha256": built["schedule_sha256"],
        "history_row_count": len(built["history_rows"]),
        "source_seasons": [args.start_season, args.end_season],
        "evidence_role": "REUSED_RESEARCH_HISTORY_NOT_UNTOUCHED_PROMOTION_EVIDENCE",
        "location_validation": report,
        "preopening_stadium_bridges": built["preopening_stadium_bridges"],
        "starting_qb_gap_count_before_override": len(
            built["starting_qb_gaps_before_override"]
        ),
        "starter_overrides": built["starter_overrides"],
        "environment_exclusions": built["environment_exclusions"],
        "authority": {
            "research_only": True,
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "bettor_facing_release": False,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "location_gate_pass": report["location_gate_pass"],
                "history_row_count": len(built["history_rows"]),
                "source_manifest_sha256": built["manifest_sha256"],
                "authority": payload["authority"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
