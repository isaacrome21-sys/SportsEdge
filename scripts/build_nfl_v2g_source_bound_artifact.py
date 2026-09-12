#!/usr/bin/env python3
"""Build a deterministic, source-bound NFL V2G research artifact.

The builder consumes immutable schedule and nflverse play-by-play files already
present on disk. Every source must be named and SHA-256-bound by the canonical
SportsEdge NFL source manifest. Historical 2016-2025 data remain research-only;
this script has no promotion, Model_P, eligibility, staking, or OFFICIAL authority.
"""
from __future__ import annotations

import argparse
import csv
import gzip
from hashlib import sha1, sha256
import json
from pathlib import Path
import sys
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.nfl.history import parse_schedule_csv
from sportsedge.sports.nfl.m2_v2g_artifact import (
    artifact_sha256,
    build_v2g_research_artifact,
    canonical_bytes,
    validate_v2g_research_artifact,
)
from sportsedge.sports.nfl.m2_v2g_candidate import (
    NFL_M2_V2G_CANDIDATE_MODEL_ID,
    build_nfl_v2g_game_event_rows,
    fit_nfl_m2_v2g_candidate,
)
from sportsedge.sports.nfl.source_manifest import manifest_sha256

PBP_FIELDS = {
    "game_id", "posteam", "drive", "touchdown", "td_team",
    "play_type", "field_goal_result",
}
SCHEDULE_FIELDS = {"game_id", "season", "week", "game_type", "home_team", "away_team"}
CANDIDATE_PATH = ROOT / "sportsedge/sports/nfl/m2_v2g_candidate.py"
FREEZE_PATH = ROOT / "config/research/nfl_v2g_implementation_freeze_2026-09-12.json"
TEAM_ALIAS_POLICY = "NFLVERSE_PBP_CURRENT_FRANCHISE_CODE_V1"
SCHEDULE_TO_PBP_TEAM_ALIAS = {"OAK": "LV", "SD": "LAC"}


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha1(path: Path) -> str:
    raw = path.read_bytes()
    header = f"blob {len(raw)}\0".encode("ascii")
    return sha1(header + raw).hexdigest()


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _read_projected(path: Path, fields: set[str]) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"NFL_V2G_SOURCE_HEADER_MISSING:{path}")
        missing = sorted(fields - set(reader.fieldnames))
        if missing:
            raise ValueError(f"NFL_V2G_SOURCE_FIELDS_MISSING:{path}:{','.join(missing)}")
        return [{name: row.get(name, "") for name in fields} for row in reader]


def _identity_scoped_pbp(rows: Iterable[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    """Keep only rows that can belong to an offensive possession."""
    kept: list[dict[str, str]] = []
    dropped = 0
    for raw in rows:
        row = dict(raw)
        posteam = str(row.get("posteam") or "").strip()
        drive = str(row.get("drive") or "").strip()
        if posteam and drive:
            kept.append(row)
            continue

        play_type = str(row.get("play_type") or "").strip().lower()
        fg_made = play_type == "field_goal" and str(row.get("field_goal_result") or "").strip().lower() == "made"
        try:
            touchdown = float(row.get("touchdown") or 0.0) == 1.0
        except (TypeError, ValueError):
            touchdown = False
        if fg_made:
            raise ValueError(f"NFL_V2G_SCORING_EVENT_IDENTITY_MISSING:{row.get('game_id')}:FIELD_GOAL")
        if touchdown and play_type not in {"kickoff", "punt"}:
            raise ValueError(f"NFL_V2G_SCORING_EVENT_IDENTITY_MISSING:{row.get('game_id')}:TOUCHDOWN:{play_type}")
        dropped += 1
    return kept, dropped


def _normalize_schedule_team_aliases(
    schedule_rows: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Normalize only source-proven historical franchise codes used by nflverse PBP.

    The mapping is deliberately explicit and minimal. It was observed directly in
    the hash-bound hosted 2016-2025 corpus: schedule OAK corresponds to PBP LV and
    schedule SD corresponds to PBP LAC. No fuzzy or inferred mapping is allowed.
    """
    normalized: list[dict[str, Any]] = []
    applications: list[dict[str, str]] = []
    for raw in schedule_rows:
        row = dict(raw)
        game_id = str(row.get("game_id") or "").strip()
        for field in ("home_team", "away_team"):
            original = str(row.get(field) or "").strip()
            mapped = SCHEDULE_TO_PBP_TEAM_ALIAS.get(original, original)
            row[field] = mapped
            if mapped != original:
                applications.append({
                    "game_id": game_id,
                    "field": field,
                    "from": original,
                    "to": mapped,
                })
        normalized.append(row)
    applications.sort(key=lambda item: (item["game_id"], item["field"], item["from"], item["to"]))
    return normalized, applications


def _team_identity_mismatches(
    schedule_rows: Iterable[dict[str, Any]],
    pbp_rows: Iterable[dict[str, str]],
) -> list[dict[str, Any]]:
    expected: dict[str, tuple[str, str]] = {}
    for raw in schedule_rows:
        game_id = str(raw.get("game_id") or "").strip()
        if not game_id or str(raw.get("game_type") or "REG").upper() != "REG":
            continue
        expected[game_id] = (
            str(raw.get("home_team") or "").strip(),
            str(raw.get("away_team") or "").strip(),
        )
    observed: dict[str, set[str]] = {}
    for raw in pbp_rows:
        game_id = str(raw.get("game_id") or "").strip()
        posteam = str(raw.get("posteam") or "").strip()
        if game_id in expected and posteam:
            observed.setdefault(game_id, set()).add(posteam)

    mismatches: list[dict[str, Any]] = []
    for game_id, teams in sorted(expected.items()):
        expected_set = {team for team in teams if team}
        observed_set = observed.get(game_id, set())
        if not observed_set:
            continue
        if not expected_set.issubset(observed_set):
            mismatches.append({
                "game_id": game_id,
                "expected_teams": sorted(expected_set),
                "observed_possession_teams": sorted(observed_set),
                "missing_expected_teams": sorted(expected_set - observed_set),
                "unexpected_observed_teams": sorted(observed_set - expected_set),
            })
    return mismatches


def _load_manifest(path: Path) -> tuple[dict[str, Any], dict[str, str], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or payload.get("sport") != "nfl":
        raise ValueError("NFL_V2G_SOURCE_MANIFEST_SCHEMA_INVALID")
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("NFL_V2G_SOURCE_MANIFEST_EMPTY")
    expected: dict[str, str] = {}
    for raw in rows:
        if not isinstance(raw, dict):
            raise ValueError("NFL_V2G_SOURCE_MANIFEST_ROW_INVALID")
        name = str(raw.get("name") or "").strip()
        value = str(raw.get("sha256") or "").strip().lower()
        if not name or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise ValueError(f"NFL_V2G_SOURCE_MANIFEST_ROW_INVALID:{name}")
        if name in expected:
            raise ValueError(f"NFL_V2G_SOURCE_MANIFEST_DUPLICATE:{name}")
        expected[name] = value
    return payload, expected, manifest_sha256(payload)


def _verify_source(path: Path, expected: str | None, label: str) -> None:
    if expected is None:
        raise ValueError(f"NFL_V2G_SOURCE_MANIFEST_ENTRY_MISSING:{label}")
    if not path.is_file():
        raise ValueError(f"NFL_V2G_SOURCE_FILE_MISSING:{label}")
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(f"NFL_V2G_SOURCE_SHA256_MISMATCH:{label}")


def _pbp_path(directory: Path, season: int) -> Path:
    candidates = [
        directory / f"play_by_play_{season}.csv.gz",
        directory / f"play_by_play_{season}.csv",
    ]
    existing = [path for path in candidates if path.is_file()]
    if len(existing) != 1:
        raise ValueError(f"NFL_V2G_PBP_FILE_COUNT:{season}:{len(existing)}")
    return existing[0]


def _canonical_training_rows(rows: Iterable[dict[str, Any]]) -> bytes:
    normalized = sorted((dict(row) for row in rows), key=lambda row: str(row.get("game_id") or ""))
    return b"".join(
        (json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")
        for row in normalized
    )


def build(
    *, schedule_file: Path, pbp_dir: Path, source_manifest: Path,
    start_season: int, end_season: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if start_season < 2016 or end_season > 2025 or end_season < start_season:
        raise ValueError("NFL_V2G_RESEARCH_SEASON_RANGE_INVALID")

    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("candidate_id") != NFL_M2_V2G_CANDIDATE_MODEL_ID:
        raise ValueError("NFL_V2G_FREEZE_CANDIDATE_MISMATCH")
    expected_blob = str(freeze.get("candidate_source_git_blob_sha1") or "").strip().lower()
    actual_blob = _git_blob_sha1(CANDIDATE_PATH)
    if actual_blob != expected_blob:
        raise ValueError("NFL_V2G_FROZEN_CANDIDATE_SOURCE_BLOB_MISMATCH")

    _manifest, expected, source_manifest_sha = _load_manifest(source_manifest)
    _verify_source(schedule_file, expected.get("schedule"), "schedule")

    schedule_raw = parse_schedule_csv(schedule_file.read_text(encoding="utf-8-sig"))
    schedule_rows: list[dict[str, Any]] = []
    for raw in schedule_raw:
        try:
            season = int(float(raw.get("season") or 0))
        except (TypeError, ValueError):
            continue
        if not (start_season <= season <= end_season):
            continue
        schedule_rows.append({field: raw.get(field) for field in SCHEDULE_FIELDS})
    schedule_rows, alias_applications = _normalize_schedule_team_aliases(schedule_rows)

    pbp_rows: list[dict[str, str]] = []
    ignored_unscoped_rows = 0
    source_files: dict[str, str] = {"schedule": _sha256_file(schedule_file)}
    for season in range(start_season, end_season + 1):
        path = _pbp_path(pbp_dir, season)
        label = f"pbp_{season}"
        _verify_source(path, expected.get(label), label)
        source_files[label] = _sha256_file(path)
        scoped, dropped = _identity_scoped_pbp(_read_projected(path, PBP_FIELDS))
        pbp_rows.extend(scoped)
        ignored_unscoped_rows += dropped

    identity_mismatches = _team_identity_mismatches(schedule_rows, pbp_rows)
    if identity_mismatches:
        raise ValueError(
            "NFL_V2G_TEAM_IDENTITY_MISMATCHES:" +
            json.dumps(identity_mismatches, sort_keys=True, separators=(",", ":"))
        )

    event_rows = build_nfl_v2g_game_event_rows(schedule_rows, pbp_rows)
    event_rows = [row for row in event_rows if start_season <= int(row["season"]) <= end_season]
    if len(event_rows) < 2:
        raise ValueError("NFL_V2G_EVENT_ROWS_INSUFFICIENT")

    training_bytes = _canonical_training_rows(event_rows)
    training_sha = sha256(training_bytes).hexdigest()
    model = fit_nfl_m2_v2g_candidate(event_rows)
    artifact_a = build_v2g_research_artifact(
        model,
        implementation_freeze=freeze,
        training_event_rows_sha256=training_sha,
        source_manifest_sha256=source_manifest_sha,
    )
    artifact_b = build_v2g_research_artifact(
        model,
        implementation_freeze=freeze,
        training_event_rows_sha256=training_sha,
        source_manifest_sha256=source_manifest_sha,
    )
    if canonical_bytes(artifact_a) != canonical_bytes(artifact_b):
        raise ValueError("NFL_V2G_ARTIFACT_BYTE_REPLAY_MISMATCH")
    validated_sha = validate_v2g_research_artifact(artifact_a, implementation_freeze=freeze)
    if validated_sha != artifact_sha256(artifact_a):
        raise ValueError("NFL_V2G_ARTIFACT_HASH_REPLAY_MISMATCH")

    report = {
        "schema_version": "NFL_M2_V2G_SOURCE_BOUND_BUILD_REPORT_V1",
        "status": "RESEARCH_ARTIFACT_BUILT_DETERMINISTICALLY",
        "candidate_id": NFL_M2_V2G_CANDIDATE_MODEL_ID,
        "season_range": [start_season, end_season],
        "event_row_count": len(event_rows),
        "ignored_unscoped_pbp_row_count": ignored_unscoped_rows,
        "team_alias_policy": TEAM_ALIAS_POLICY,
        "team_alias_map": dict(sorted(SCHEDULE_TO_PBP_TEAM_ALIAS.items())),
        "team_alias_application_count": len(alias_applications),
        "team_alias_applications": alias_applications,
        "training_event_rows_sha256": training_sha,
        "source_manifest_sha256": source_manifest_sha,
        "source_files_sha256": source_files,
        "candidate_source_git_blob_sha1": actual_blob,
        "artifact_sha256": validated_sha,
        "byte_determinism": "PASS",
        "historical_data_role": "REUSED_RESEARCH_HISTORY_NOT_FINAL_HOLDOUT",
        "promotion_authority": False,
        "production_model_changed": False,
        "market_eligibility_changed": False,
        "may_create_model_p": False,
        "official_status_granted": False,
    }
    return artifact_a, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-file", type=Path, required=True)
    parser.add_argument("--pbp-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--start-season", type=int, default=2016)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--artifact-out", type=Path, default=Path("artifacts/football/nfl_m2_v2g_research_artifact.json"))
    parser.add_argument("--report-out", type=Path, default=Path("artifacts/football/nfl_m2_v2g_source_bound_build_report.json"))
    args = parser.parse_args()

    try:
        artifact, report = build(
            schedule_file=args.schedule_file,
            pbp_dir=args.pbp_dir,
            source_manifest=args.source_manifest,
            start_season=args.start_season,
            end_season=args.end_season,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({
            "status": "BLOCKED_SOURCE_BOUND_V2G_ARTIFACT_BUILD",
            "reason": str(exc),
            "promotion_authority": False,
            "may_create_model_p": False,
        }, sort_keys=True))
        return 2

    args.artifact_out.parent.mkdir(parents=True, exist_ok=True)
    args.report_out.parent.mkdir(parents=True, exist_ok=True)
    args.artifact_out.write_bytes(canonical_bytes(artifact))
    args.report_out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
