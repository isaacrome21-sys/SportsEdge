#!/usr/bin/env python3
"""Run isolated NFL V2E validation on exact frozen production-history inputs."""
from __future__ import annotations

import argparse
import json
from math import isfinite
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
    apply_pinned_starting_qb_overrides,
    audit_starting_qb_coverage,
    bridge_preopening_away_origins,
)
from scripts.run_nfl_v2_candidate_validation import _assert_source, _verified_manifest
from sportsedge.sports.nfl.history import normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.m2_history_features import fit_nfl_prior_decay_curves
from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows
from sportsedge.sports.nfl.m2_v2e_candidate import NFL_M2_V2E_PIT_STATE_FIELDS
from sportsedge.sports.nfl.m2_v2e_drives import (
    V2E_TEAM_ALIAS_POLICY,
    build_v2e_drive_training_rows,
)
from sportsedge.sports.nfl.m2_v2e_validation import build_nfl_m2_v2e_candidate_evidence

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_V2E_PBP_FIELDS = set(_PBP_FIELDS) | {
    "drive",
    "touchdown",
    "td_team",
    "extra_point_result",
    "two_point_conv_result",
    "field_goal_result",
    "safety",
}


def _identity_schedule(schedule: list[dict], *, allowed_game_ids: set[str] | None = None) -> list[dict]:
    """Return market-blind game identities, optionally restricted to retained history rows.

    V2E drive targets are training/evaluation targets for the exact PIT-safe
    production-history cohort. Requiring drive evidence for schedule games that
    the production history builder already excluded would make an unrelated
    source-quality exclusion block the diagnostic. Retained games still fail
    closed in ``build_v2e_drive_training_rows`` if either side lacks drive data.
    """
    rows = [
        {
            "game_id": row.get("game_id"),
            "season": row.get("season"),
            "home_team": row.get("home_team"),
            "away_team": row.get("away_team"),
        }
        for row in schedule
        if str(row.get("game_type") or "REG").upper() == "REG"
        and (allowed_game_ids is None or str(row.get("game_id") or "") in allowed_game_ids)
    ]
    if allowed_game_ids is not None:
        observed = {str(row.get("game_id") or "") for row in rows}
        missing = sorted(allowed_game_ids - observed)
        if missing:
            raise SystemExit(f"NFL_M2_V2E_RETAINED_SCHEDULE_IDENTITY_MISSING:{missing[0]}")
    return rows


def _pit_state(features: object, *, side: str, game_id: str) -> dict[str, float]:
    if not isinstance(features, dict):
        raise SystemExit(f"NFL_M2_V2E_PIT_FEATURES_MISSING:{game_id}:{side}")
    state: dict[str, float] = {}
    for key in NFL_M2_V2E_PIT_STATE_FIELDS:
        if key not in features:
            raise SystemExit(f"NFL_M2_V2E_PIT_STATE_FIELD_MISSING:{game_id}:{side}:{key}")
        try:
            value = float(features[key])
        except (TypeError, ValueError) as exc:
            raise SystemExit(f"NFL_M2_V2E_PIT_STATE_FIELD_INVALID:{game_id}:{side}:{key}") from exc
        if not isfinite(value):
            raise SystemExit(f"NFL_M2_V2E_PIT_STATE_FIELD_INVALID:{game_id}:{side}:{key}")
        state[key] = value
    return state


def _join_drive_targets(history_rows: list[dict], drive_rows: list[dict]) -> list[dict]:
    drive_by_game = {str(row.get("game_id") or ""): dict(row) for row in drive_rows}
    if "" in drive_by_game or len(drive_by_game) != len(drive_rows):
        raise SystemExit("NFL_M2_V2E_DRIVE_IDENTITY_INVALID")
    combined: list[dict] = []
    target_prefixes = (
        "home_drives", "away_drives",
        "home_td_", "away_td_", "home_fg", "away_fg",
        "home_def_td_7_allowed", "away_def_td_7_allowed",
        "home_safety_allowed", "away_safety_allowed",
        "home_no_score", "away_no_score",
    )
    for raw in history_rows:
        row = dict(raw)
        game_id = str(row.get("game_id") or "")
        target = drive_by_game.get(game_id)
        if target is None:
            raise SystemExit(f"NFL_M2_V2E_DRIVE_TARGET_MISSING:{game_id}")
        for key, value in target.items():
            if key in {
                "game_id", "season", "home_team", "away_team", "source_contract",
                "team_alias_policy", "team_alias_application_count",
            }:
                continue
            if key.startswith(target_prefixes):
                row[key] = value

        # First-slice V2E state is frozen before outer evaluation and comes only
        # from the existing PIT production feature row. It conditions both drive
        # volume and scoring-event mix; no market/evaluation field is included.
        row["home_state"] = _pit_state(row.get("home_features"), side="home", game_id=game_id)
        row["away_state"] = _pit_state(row.get("away_features"), side="away", game_id=game_id)
        combined.append(row)
    return combined


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
    parser.add_argument("--path-count", type=int, default=4096)
    parser.add_argument("--neutral-site-policy", choices=("error", "exclude_from_evaluation"), default="exclude_from_evaluation")
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_m2_v2e_candidate_validation.json"))
    args = parser.parse_args()

    git_sha = str(args.git_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("NFL_M2_V2E_GIT_SHA_INVALID")
    if args.end_season < args.start_season or args.start_season < 2016:
        raise SystemExit("NFL_M2_V2E_SEASON_RANGE_INVALID")
    if args.path_count < 256:
        raise SystemExit("NFL_M2_V2E_PATH_COUNT_TOO_SMALL")

    manifest_payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
    manifest_hash, expected_sources = _verified_manifest(manifest_payload)

    pbp_files = _files(args.pbp_dir, "play_by_play_{season}.{ext}", args.start_season, args.end_season)
    participation_files = _files(args.participation_dir, "pbp_participation_{season}.{ext}", args.start_season, args.end_season)
    depth_files = _files(args.depth_dir, "depth_charts_{season}.{ext}", args.start_season, args.end_season)
    required = {"schedule": args.schedule_file, "stadiums": args.stadium_file, "starter_overrides": args.starter_override_file}
    for season, path in zip(range(args.start_season, args.end_season + 1), pbp_files):
        required[f"pbp_{season}"] = path
    for season, path in zip(range(args.start_season, args.end_season + 1), participation_files):
        required[f"participation_{season}"] = path
    for season, path in zip(range(args.start_season, args.end_season + 1), depth_files):
        required[f"depth_{season}"] = path
    for name, path in required.items():
        expected = expected_sources.get(name)
        if expected is None:
            raise SystemExit(f"NFL_M2_V2E_SOURCE_MANIFEST_ENTRY_MISSING:{name}")
        _assert_source(path, expected, name)

    schedule = normalize_nfl_rows(
        parse_schedule_csv(args.schedule_file.read_text(encoding="utf-8-sig")),
        range(args.start_season, args.end_season + 1),
    )
    pbp: list[dict[str, str]] = []
    participation: list[dict[str, str]] = []
    depth: list[dict[str, str]] = []
    _extend(pbp, pbp_files, _V2E_PBP_FIELDS)
    _extend(participation, participation_files, _PARTICIPATION_FIELDS)
    _extend(depth, depth_files, _DEPTH_FIELDS)
    raw_stadiums = _read_projected(args.stadium_file, _STADIUM_FIELDS)
    stadiums, stadium_bridges = bridge_preopening_away_origins(schedule, raw_stadiums)
    prior_curves = fit_nfl_prior_decay_curves(schedule, pbp, min_train_seasons=args.min_train_seasons, weeks=range(1, 7))

    override_payload = json.loads(args.starter_override_file.read_text(encoding="utf-8"))
    before = audit_starting_qb_coverage(schedule, depth, eligible_seasons=prior_curves)
    depth, applied = apply_pinned_starting_qb_overrides(schedule, depth, override_payload)
    after = audit_starting_qb_coverage(schedule, depth, eligible_seasons=prior_curves)
    if after:
        raise SystemExit(f"NFL_M2_V2E_STARTING_QB_COVERAGE_GAPS:{len(after)}")

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
        raise SystemExit("NFL_M2_V2E_HISTORY_ROWS_EMPTY")

    retained_game_ids = {str(row.get("game_id") or "") for row in history_rows}
    if "" in retained_game_ids or len(retained_game_ids) != len(history_rows):
        raise SystemExit("NFL_M2_V2E_HISTORY_GAME_IDENTITY_INVALID")
    drive_schedule = _identity_schedule(schedule, allowed_game_ids=retained_game_ids)
    drive_rows = build_v2e_drive_training_rows(drive_schedule, pbp)
    alias_application_count = sum(int(row.get("team_alias_application_count") or 0) for row in drive_rows)
    alias_policies = {str(row.get("team_alias_policy") or "") for row in drive_rows}
    if alias_policies != {V2E_TEAM_ALIAS_POLICY}:
        raise SystemExit("NFL_M2_V2E_TEAM_ALIAS_POLICY_MISMATCH")
    combined_rows = _join_drive_targets(history_rows, drive_rows)
    evidence = build_nfl_m2_v2e_candidate_evidence(
        combined_rows,
        source_manifest_sha256=manifest_hash,
        min_train_seasons=args.min_train_seasons,
        path_count=args.path_count,
    )
    evidence.update({
        "code_git_sha": git_sha,
        "season_range": [args.start_season, args.end_season],
        "point_in_time_history_row_count": len(history_rows),
        "drive_target_row_count": len(drive_rows),
        "combined_row_count": len(combined_rows),
        "drive_target_scope": "EXACT_RETAINED_PRODUCTION_HISTORY_GAME_IDS",
        "drive_team_alias_policy": V2E_TEAM_ALIAS_POLICY,
        "drive_team_alias_application_count": alias_application_count,
        "pit_state_fields": list(NFL_M2_V2E_PIT_STATE_FIELDS),
        "pit_state_conditions_drive_volume": True,
        "pit_state_conditions_scoring_event_mix": True,
        "neutral_site_policy": args.neutral_site_policy,
        "source_manifest_path": str(args.source_manifest),
        "starting_qb_coverage_issue_count_before_override": len(before),
        "starting_qb_coverage_issue_count": 0,
        "starting_qb_override_count": len(applied),
        "stadium_home_origin_bridge_count": len(stadium_bridges),
        "production_registry_consumes_this_artifact": False,
        "outer_history_status": "DEVELOPMENT_FALSIFICATION_ONLY_ALREADY_OBSERVED_FOLDS",
        "prospective_confirmation_required_for_promotion": True,
    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "V2E_DIAGNOSTIC_COMPLETE",
        "history_rows": len(history_rows),
        "drive_rows": len(drive_rows),
        "drive_team_alias_policy": V2E_TEAM_ALIAS_POLICY,
        "drive_team_alias_application_count": alias_application_count,
        "candidate_historical_evidence": evidence["candidate_historical_evidence"],
        "signed_key_probability": evidence["candidate_distribution_profile"]["signed_key_probability"],
        "promotion_eligible": False,
        "production_registry_consumes_this_artifact": False,
        "prospective_confirmation_required_for_promotion": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
