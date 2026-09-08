#!/usr/bin/env python3
"""Run exact production NFL M2 walk-forward validation from frozen public data."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime, timedelta
import gzip
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Iterable

# Direct execution (``python scripts/...``) places only ``scripts`` at the
# front of sys.path. Add the repository root so this CLI works identically on a
# clean hosted runner without changing any validation or model semantics.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.history import normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.m2 import fit_nfl_m2_score_model
from sportsedge.sports.nfl.m2_history_features import _game_start, fit_nfl_prior_decay_curves, select_starting_qb
from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows
from sportsedge.sports.nfl.model_artifact import build_nfl_m2_model_artifact
from sportsedge.sports.nfl.production_validation import build_production_nfl_validation_evidence
from sportsedge.sports.nfl.source_manifest import build_nfl_source_manifest, manifest_sha256

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PBP_FIELDS = {"game_id", "play_id", "posteam", "defteam", "epa", "qb_epa", "pass", "rush", "qb_dropback", "passer_player_id", "passer_id", "yards_gained", "play_type"}
_PARTICIPATION_FIELDS = {"nflverse_game_id", "game_id", "play_id", "was_pressure"}
_DEPTH_FIELDS = {"season", "club_code", "team", "week", "game_type", "depth_team", "position", "depth_position", "gsis_id", "dt", "pos_abb", "pos_rank"}
_STADIUM_FIELDS = {"team_fastr", "team", "stadium", "first_game_date", "last_game_date", "lat", "lon", "tz_offset"}
_MAX_PREOPENING_AWAY_ORIGIN_GAP_DAYS = 28
_STARTER_OVERRIDE_CONTRACT = "PINNED_PREGAME_OFFICIAL_STARTER_OVERRIDE_V1"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    return path.open("r", encoding="utf-8-sig", newline="")


def _read_projected(path: Path, fields: set[str]) -> list[dict[str, str]]:
    with _open_text(path) as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"NFL_SOURCE_HEADER_MISSING:{path}")
        chosen = [name for name in reader.fieldnames if name in fields]
        if not chosen:
            raise ValueError(f"NFL_SOURCE_FIELDS_MISSING:{path}")
        return [{name: row.get(name, "") for name in chosen} for row in reader]


def _files(directory: Path, pattern: str, start: int, end: int) -> list[Path]:
    files = []
    for season in range(start, end + 1):
        candidates = [directory / pattern.format(season=season, ext="csv.gz"), directory / pattern.format(season=season, ext="csv")]
        existing = [path for path in candidates if path.exists()]
        if len(existing) != 1:
            raise ValueError(f"NFL_FROZEN_SOURCE_FILE_COUNT:{season}:{pattern}:{len(existing)}")
        files.append(existing[0])
    return files


def _extend(target: list[dict[str, str]], paths: Iterable[Path], fields: set[str]) -> None:
    for path in paths:
        target.extend(_read_projected(path, fields))


def _date_value(value) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _stadium_team(row: dict[str, str]) -> str:
    return str(row.get("team_fastr") or row.get("team") or "").strip()


def _stadium_geo_complete(row: dict[str, str]) -> bool:
    try:
        float(row.get("lat") or "")
        float(row.get("lon") or "")
        float(row.get("tz_offset") or "")
    except (TypeError, ValueError):
        return False
    return True


def _stadium_active(row: dict[str, str], *, team: str, gameday: date) -> bool:
    if _stadium_team(row) != team or not _stadium_geo_complete(row):
        return False
    first = _date_value(row.get("first_game_date")) or date.min
    last = _date_value(row.get("last_game_date")) or date.max
    return first <= gameday <= last


def bridge_preopening_away_origins(
    schedule_rows: Iterable[dict],
    stadium_rows: Iterable[dict[str, str]],
    *,
    max_gap_days: int = _MAX_PREOPENING_AWAY_ORIGIN_GAP_DAYS,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Bridge only bounded pre-opening *away-team origin* gaps.

    The stadium source dates a new venue from the first NFL game played there.
    A relocated/new-stadium team can therefore have an away game a few days
    before its first home game with no active stadium row. For travel features,
    that is an origin-proxy gap, not an unknown game venue.

    We bridge only that narrow case: an away team with no active origin may use
    one unique future stadium row whose first-game date is at most ``max_gap``
    days away. The synthetic row ends the day before the source row begins, so
    it can never override the source interval. Home venues are never bridged.
    Missing, distant, or ambiguous mappings remain fail-closed in the canonical
    history builder.
    """
    if max_gap_days < 0:
        raise ValueError("NFL_STADIUM_BRIDGE_GAP_INVALID")

    base = [dict(row) for row in stadium_rows]
    resolved = [dict(row) for row in base]
    bridges: list[dict[str, object]] = []
    games = [dict(row) for row in schedule_rows if str(row.get("game_type") or "REG").upper() == "REG"]
    games.sort(key=lambda row: (str(row.get("gameday") or row.get("game_date") or ""), str(row.get("game_id") or "")))

    for game in games:
        gameday = _date_value(game.get("gameday") or game.get("game_date"))
        team = str(game.get("away_team") or "").strip()
        if gameday is None or not team:
            continue
        if any(_stadium_active(row, team=team, gameday=gameday) for row in resolved):
            continue

        future: list[tuple[date, dict[str, str]]] = []
        for row in base:
            if _stadium_team(row) != team or not _stadium_geo_complete(row):
                continue
            first = _date_value(row.get("first_game_date"))
            if first is None:
                continue
            gap = (first - gameday).days
            if 0 < gap <= max_gap_days:
                future.append((first, row))
        if not future:
            continue

        earliest = min(first for first, _ in future)
        selected = [row for first, row in future if first == earliest]
        if len(selected) != 1:
            raise ValueError(f"NFL_STADIUM_BRIDGE_AMBIGUOUS:{team}:{gameday.isoformat()}:{earliest.isoformat()}")

        source_row = selected[0]
        bridge = dict(source_row)
        bridge["first_game_date"] = gameday.isoformat()
        bridge["last_game_date"] = (earliest - timedelta(days=1)).isoformat()
        resolved.append(bridge)
        bridges.append({
            "team": team,
            "game_id": str(game.get("game_id") or ""),
            "away_game_date": gameday.isoformat(),
            "stadium": str(source_row.get("stadium") or ""),
            "source_first_game_date": earliest.isoformat(),
            "bridge_last_date": bridge["last_game_date"],
            "gap_days": (earliest - gameday).days,
            "reason": "PRE_OPENING_AWAY_TEAM_HOME_ORIGIN_PROXY",
        })

    return resolved, bridges


def _depth_row_season(row: dict[str, str]) -> int | None:
    value = row.get("season")
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _depth_scope(rows: Iterable[dict[str, str]], *, team: str, season: int) -> list[dict[str, str]]:
    scope: list[dict[str, str]] = []
    for raw in rows:
        row = dict(raw)
        row_team = str(row.get("team") or row.get("club_code") or "").strip()
        if row_team != team:
            continue
        if row.get("dt") not in (None, "") or _depth_row_season(row) == int(season):
            scope.append(row)
    return scope


def _aware_datetime(value: object, *, error_code: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(error_code) from None
    if parsed.tzinfo is None:
        raise ValueError(error_code)
    return parsed


def apply_pinned_starting_qb_overrides(
    schedule_rows: Iterable[dict],
    depth_rows: Iterable[dict[str, str]],
    payload: dict,
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    """Apply only exact, pregame, source-pinned overrides to true depth gaps.

    Overrides are a last-mile source repair, not a model fallback. An override is
    legal only when the canonical selector currently reports a missing starter,
    the row matches one exact scheduled team/game/week, and the cited source was
    published before kickoff. Existing or ambiguous upstream starter evidence is
    never overwritten.
    """
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("NFL_STARTER_OVERRIDE_SCHEMA_INVALID")
    if payload.get("sport") != "nfl" or payload.get("contract") != _STARTER_OVERRIDE_CONTRACT:
        raise ValueError("NFL_STARTER_OVERRIDE_CONTRACT_INVALID")
    overrides = payload.get("overrides")
    if not isinstance(overrides, list):
        raise ValueError("NFL_STARTER_OVERRIDE_ROWS_INVALID")

    schedule = [dict(row) for row in schedule_rows]
    by_game = {str(row.get("game_id") or "").strip(): row for row in schedule if str(row.get("game_id") or "").strip()}
    resolved = [dict(row) for row in depth_rows]
    applied: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()

    for raw in overrides:
        if not isinstance(raw, dict):
            raise ValueError("NFL_STARTER_OVERRIDE_ROW_INVALID")
        game_id = str(raw.get("game_id") or "").strip()
        team = str(raw.get("team") or "").strip()
        gsis_id = str(raw.get("gsis_id") or "").strip()
        source_uri = str(raw.get("source_uri") or "").strip()
        reason = str(raw.get("reason") or "").strip()
        try:
            season = int(raw.get("season"))
            week = int(raw.get("week"))
        except (TypeError, ValueError):
            raise ValueError("NFL_STARTER_OVERRIDE_IDENTITY_INVALID") from None
        key = (game_id, team)
        if not all((game_id, team, gsis_id, source_uri, reason)) or key in seen:
            raise ValueError("NFL_STARTER_OVERRIDE_IDENTITY_INVALID")
        seen.add(key)

        game = by_game.get(game_id)
        if game is None:
            raise ValueError(f"NFL_STARTER_OVERRIDE_GAME_MISSING:{game_id}")
        if int(game.get("season") or -1) != season or int(game.get("week") or -1) != week:
            raise ValueError(f"NFL_STARTER_OVERRIDE_SCHEDULE_MISMATCH:{game_id}:{team}")
        if team not in {str(game.get("home_team") or "").strip(), str(game.get("away_team") or "").strip()}:
            raise ValueError(f"NFL_STARTER_OVERRIDE_TEAM_MISMATCH:{game_id}:{team}")

        start = _game_start(game)
        published = _aware_datetime(raw.get("source_published_ts"), error_code="NFL_STARTER_OVERRIDE_SOURCE_TIME_INVALID")
        if published >= start:
            raise ValueError(f"NFL_STARTER_OVERRIDE_NOT_PREGAME:{game_id}:{team}")

        scope = _depth_scope(resolved, team=team, season=season)
        try:
            existing = select_starting_qb(scope, team=team, season=season, week=week, game_start_ts=start)
        except ValueError as exc:
            error = str(exc)
            if not error.startswith("NFL_STARTING_QB_MISSING:"):
                raise ValueError(f"NFL_STARTER_OVERRIDE_REQUIRES_MISSING:{game_id}:{team}:{error}") from exc
        else:
            raise ValueError(f"NFL_STARTER_OVERRIDE_NOT_NEEDED:{game_id}:{team}:{existing}")

        synthetic = {
            "season": str(season),
            "club_code": team,
            "team": team,
            "week": str(week),
            "game_type": "REG",
            "depth_team": "1",
            "position": "QB",
            "depth_position": "QB",
            "gsis_id": gsis_id,
            "dt": "",
            "pos_abb": "",
            "pos_rank": "",
        }
        resolved.append(synthetic)
        selected = select_starting_qb(
            _depth_scope(resolved, team=team, season=season),
            team=team,
            season=season,
            week=week,
            game_start_ts=start,
        )
        if selected != gsis_id:
            raise ValueError(f"NFL_STARTER_OVERRIDE_RESOLUTION_MISMATCH:{game_id}:{team}:{selected}")

        applied.append({
            "game_id": game_id,
            "season": season,
            "week": week,
            "team": team,
            "gsis_id": gsis_id,
            "source_uri": source_uri,
            "source_published_ts": published.isoformat(),
            "identity_source_uri": str(raw.get("identity_source_uri") or "").strip(),
            "reason": reason,
        })

    return resolved, applied


def audit_starting_qb_coverage(
    schedule_rows: Iterable[dict],
    depth_rows: Iterable[dict[str, str]],
    *,
    eligible_seasons: Iterable[int],
) -> list[dict[str, object]]:
    """Return every missing/ambiguous required PIT starter in one deterministic pass.

    This is diagnostic only. It calls the exact production ``select_starting_qb``
    contract and never supplies a replacement starter. Its narrowed per-game
    input is lossless for that selector: every timestamped row for the team is
    retained because timestamped selection is date-based, while weekly rows are
    retained only for the requested team/season because all other weekly rows
    are rejected by the production selector's exact season/team predicates.
    """
    eligible = {int(season) for season in eligible_seasons}
    timestamped_by_team: dict[str, list[dict[str, str]]] = {}
    weekly_by_team_season: dict[tuple[str, int], list[dict[str, str]]] = {}
    for raw in depth_rows:
        row = dict(raw)
        team = str(row.get("team") or row.get("club_code") or "").strip()
        if not team:
            continue
        if row.get("dt") not in (None, ""):
            timestamped_by_team.setdefault(team, []).append(row)
        row_season = _depth_row_season(row)
        if row_season is not None:
            weekly_by_team_season.setdefault((team, row_season), []).append(row)

    games = [
        dict(row) for row in schedule_rows
        if str(row.get("game_type") or "REG").upper() == "REG" and int(row.get("season") or -1) in eligible
    ]
    games.sort(key=lambda row: (_game_start(row), str(row.get("game_id") or "")))
    issues: list[dict[str, object]] = []
    for game in games:
        season = int(game["season"])
        week = int(game["week"])
        game_id = str(game.get("game_id") or "").strip()
        start = _game_start(game)
        for side in ("home", "away"):
            team = str(game.get(f"{side}_team") or "").strip()
            scope = [
                *timestamped_by_team.get(team, ()),
                *weekly_by_team_season.get((team, season), ()),
            ]
            try:
                select_starting_qb(scope, team=team, season=season, week=week, game_start_ts=start)
            except ValueError as exc:
                error = str(exc)
                if not error.startswith(("NFL_STARTING_QB_MISSING:", "NFL_STARTING_QB_AMBIGUOUS:")):
                    raise
                issues.append({
                    "game_id": game_id,
                    "season": season,
                    "week": week,
                    "side": side,
                    "team": team,
                    "game_start_ts": start.isoformat(),
                    "error": error,
                })
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-file", type=Path, required=True)
    parser.add_argument("--pbp-dir", type=Path, required=True)
    parser.add_argument("--participation-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--stadium-file", type=Path, required=True)
    parser.add_argument("--starter-override-file", type=Path, default=Path("config/nfl_historical_starter_overrides.json"))
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--start-season", type=int, default=2016)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--min-train-seasons", type=int, default=2)
    parser.add_argument("--ridge-alpha", type=float, default=10.0)
    parser.add_argument("--neutral-site-policy", choices=("error", "exclude_from_evaluation"), default="exclude_from_evaluation")
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_production_validation.json"))
    parser.add_argument("--manifest-out", type=Path, default=Path("artifacts/football/nfl_source_manifest.json"))
    parser.add_argument("--model-out", type=Path, default=Path("artifacts/football/nfl_m2_model.json"))
    parser.add_argument("--qb-coverage-out", type=Path, default=Path("artifacts/football/nfl_starting_qb_coverage.json"))
    args = parser.parse_args()

    git_sha = str(args.git_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("NFL_PRODUCTION_GIT_SHA_INVALID")
    if args.end_season < args.start_season:
        raise SystemExit("END_SEASON_BEFORE_START_SEASON")
    if args.start_season < 2016:
        raise SystemExit("NFL_PRODUCTION_PRESSURE_HISTORY_STARTS_2016")
    if not args.starter_override_file.exists():
        raise SystemExit("NFL_STARTER_OVERRIDE_FILE_MISSING")

    pbp_files = _files(args.pbp_dir, "play_by_play_{season}.{ext}", args.start_season, args.end_season)
    participation_files = _files(args.participation_dir, "pbp_participation_{season}.{ext}", args.start_season, args.end_season)
    depth_files = _files(args.depth_dir, "depth_charts_{season}.{ext}", args.start_season, args.end_season)
    schedule_sha = _sha(args.schedule_file)
    starter_override_sha = _sha(args.starter_override_file)
    sources = [
        {"name": "schedule", "uri": "frozen://nflverse/games.csv", "sha256": schedule_sha},
        {"name": "stadiums", "uri": "frozen://greerreNFL/Stadiums/team_stadiums.csv", "sha256": _sha(args.stadium_file)},
        {"name": "starter_overrides", "uri": f"repo://{args.starter_override_file.as_posix()}", "sha256": starter_override_sha},
    ]
    for prefix, paths in (("pbp", pbp_files), ("participation", participation_files), ("depth", depth_files)):
        for path in paths:
            season = next(token for token in path.stem.replace(".csv", "").split("_") if token.isdigit() and len(token) == 4)
            sources.append({"name": f"{prefix}_{season}", "uri": f"frozen://nflverse/{path.name}", "sha256": _sha(path)})
    manifest = build_nfl_source_manifest(sources, schedule_anchor_sha256=schedule_sha)
    manifest_hash = manifest_sha256(manifest)
    manifest_payload = dict(manifest)
    manifest_payload["manifest_sha256"] = manifest_hash
    manifest_payload["participation_attribution"] = {
        "2016_2022": "NFL NextGenStats via nflverse", "2023_plus": "FTN Data via nflverse",
        "license": "CC-BY-SA-4.0 per nflverse participation release",
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    schedule = normalize_nfl_rows(parse_schedule_csv(args.schedule_file.read_text(encoding="utf-8-sig")), range(args.start_season, args.end_season + 1))
    pbp: list[dict[str, str]] = []; participation: list[dict[str, str]] = []; depth: list[dict[str, str]] = []
    _extend(pbp, pbp_files, _PBP_FIELDS); _extend(participation, participation_files, _PARTICIPATION_FIELDS); _extend(depth, depth_files, _DEPTH_FIELDS)
    raw_stadiums = _read_projected(args.stadium_file, _STADIUM_FIELDS)
    stadiums, stadium_bridges = bridge_preopening_away_origins(schedule, raw_stadiums)
    prior_curves = fit_nfl_prior_decay_curves(schedule, pbp, min_train_seasons=args.min_train_seasons, weeks=range(1, 7))

    qb_coverage_before = audit_starting_qb_coverage(schedule, depth, eligible_seasons=prior_curves)
    try:
        starter_override_payload = json.loads(args.starter_override_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"NFL_STARTER_OVERRIDE_FILE_INVALID:{exc}") from exc
    depth, starter_overrides = apply_pinned_starting_qb_overrides(schedule, depth, starter_override_payload)
    qb_coverage_issues = audit_starting_qb_coverage(schedule, depth, eligible_seasons=prior_curves)
    qb_coverage_payload = {
        "schema_version": 2,
        "sport": "nfl",
        "code_git_sha": git_sha,
        "source_manifest_sha256": manifest_hash,
        "contract": "EXACT_PRODUCTION_SELECT_STARTING_QB_REQUIRED_FOR_EVALUATION_ROWS",
        "eligible_seasons": sorted(int(season) for season in prior_curves),
        "issue_count_before_override": len(qb_coverage_before),
        "issues_before_override": qb_coverage_before,
        "starter_override_contract": starter_override_payload.get("contract"),
        "starter_override_sha256": starter_override_sha,
        "starter_overrides_applied": starter_overrides,
        "issue_count": len(qb_coverage_issues),
        "status": "PASS" if not qb_coverage_issues else "BLOCKED",
        "issues": qb_coverage_issues,
    }
    args.qb_coverage_out.parent.mkdir(parents=True, exist_ok=True)
    args.qb_coverage_out.write_text(json.dumps(qb_coverage_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if qb_coverage_issues:
        compact = ";".join(
            f"{row['game_id']}:{row['side']}:{row['error']}" for row in qb_coverage_issues
        )
        print(json.dumps(qb_coverage_payload, sort_keys=True))
        raise SystemExit(f"NFL_STARTING_QB_COVERAGE_GAPS:{len(qb_coverage_issues)}:{compact}")

    weather_exclusions: dict[int, dict[str, int]] = {}
    history_rows = build_nfl_m2_history_rows(
        schedule, pbp, participation, depth, stadiums,
        prior_decay_curves=prior_curves, neutral_site_policy=args.neutral_site_policy,
        exclusion_report=weather_exclusions,
    )
    if not history_rows:
        raise SystemExit("NFL_PRODUCTION_HISTORY_ROWS_EMPTY")

    override_affected_games = {str(row["game_id"]) for row in qb_coverage_before}
    for row in history_rows:
        if str(row.get("game_id") or "") not in override_affected_games:
            continue
        provenance = row.get("feature_provenance")
        if not isinstance(provenance, dict):
            raise SystemExit("NFL_STARTER_OVERRIDE_PROVENANCE_MISSING")
        provenance["starter_qb"] = "NFLVERSE_DEPTH_CHART_OR_PINNED_PREGAME_OFFICIAL_OVERRIDE"
        provenance["starter_qb_override_manifest_sha256"] = starter_override_sha

    evidence = build_production_nfl_validation_evidence(
        history_rows, source_uri=f"manifest://sha256/{manifest_hash}", source_sha256=manifest_hash,
        source_manifest_sha256=manifest_hash, min_train_seasons=args.min_train_seasons, ridge_alpha=args.ridge_alpha,
    )
    evidence.update({
        "code_git_sha": git_sha, "source_manifest_sha256": manifest_hash, "schedule_anchor_sha256": schedule_sha,
        "source_manifest_path": str(args.manifest_out), "season_range": [args.start_season, args.end_season],
        "point_in_time_history_row_count": len(history_rows), "neutral_site_policy": args.neutral_site_policy,
        "stadium_home_origin_bridge_contract": "AWAY_TEAM_ONLY_UNIQUE_FUTURE_STADIUM_MAX_28_DAYS",
        "stadium_home_origin_bridges": stadium_bridges,
        "starting_qb_coverage_contract": qb_coverage_payload["contract"],
        "starting_qb_coverage_status": qb_coverage_payload["status"],
        "starting_qb_coverage_issue_count_before_override": len(qb_coverage_before),
        "starting_qb_coverage_issue_count": 0,
        "starting_qb_override_contract": starter_override_payload.get("contract"),
        "starting_qb_override_sha256": starter_override_sha,
        "starting_qb_overrides_applied": starter_overrides,
        "starting_qb_override_affected_games": sorted(override_affected_games),
        "environment_exclusion_contract": "COUNTED_BY_SEASON_REASON_NO_SILENT_ZERO_FILL",
        "environment_exclusions_by_season": {
            str(season): dict(sorted(reasons.items()))
            for season, reasons in sorted(weather_exclusions.items())
        },
        "environment_exclusion_count": sum(
            sum(reasons.values()) for reasons in weather_exclusions.values()
        ),
    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    final_model = fit_nfl_m2_score_model(history_rows, ridge_alpha=args.ridge_alpha)
    model_artifact = build_nfl_m2_model_artifact(final_model, code_git_sha=git_sha, source_manifest_sha256=manifest_hash)
    args.model_out.parent.mkdir(parents=True, exist_ok=True)
    args.model_out.write_text(json.dumps(model_artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "code_git_sha": git_sha, "model_id": evidence["model_id"], "feature_contract": evidence["feature_contract"],
        "source_manifest_sha256": manifest_hash, "history_rows": len(history_rows), "fold_count": evidence["fold_count"],
        "trained_through_season": model_artifact["trained_through_season"], "promotion_evidence": evidence["promotion_evidence"],
        "stadium_home_origin_bridge_count": len(stadium_bridges), "starting_qb_coverage_issue_count": 0,
        "starting_qb_override_count": len(starter_overrides),
        "environment_exclusion_count": sum(sum(reasons.values()) for reasons in weather_exclusions.values()),
        "environment_exclusions_by_season": {
            str(season): dict(sorted(reasons.items()))
            for season, reasons in sorted(weather_exclusions.items())
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())