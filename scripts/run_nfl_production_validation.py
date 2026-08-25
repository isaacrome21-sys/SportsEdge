#!/usr/bin/env python3
"""Run exact production NFL M2 walk-forward validation from frozen public data.

The runner consumes frozen schedule, PBP, participation, depth-chart, and
stadium CSV bytes, builds a canonical source manifest, constructs point-in-time
market-blind M2 rows, and evaluates the exact production model against M1.
Sportsbook fields remain outside feature construction.

Participation provenance: 2023+ participation data is FTN Data via nflverse;
2022 and earlier is NFL NextGenStats via nflverse. See nflverse's CC-BY-SA 4.0
attribution requirements for the participation release.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Iterable

from sportsedge.sports.nfl.history import normalize_nfl_rows, parse_schedule_csv
from sportsedge.sports.nfl.m2_history_features import fit_nfl_prior_decay_curves
from sportsedge.sports.nfl.m2_history_policy import build_nfl_m2_history_rows
from sportsedge.sports.nfl.production_validation import build_production_nfl_validation_evidence
from sportsedge.sports.nfl.source_manifest import build_nfl_source_manifest, manifest_sha256

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PBP_FIELDS = {
    "game_id", "play_id", "posteam", "defteam", "epa", "qb_epa", "pass", "rush",
    "qb_dropback", "passer_player_id", "passer_id", "yards_gained", "play_type",
}
_PARTICIPATION_FIELDS = {"nflverse_game_id", "game_id", "play_id", "was_pressure"}
_DEPTH_FIELDS = {
    "season", "club_code", "team", "week", "game_type", "depth_team", "position",
    "depth_position", "gsis_id", "dt", "pos_abb", "pos_rank",
}
_STADIUM_FIELDS = {
    "team_fastr", "team", "stadium", "first_game_date", "last_game_date", "lat", "lon", "tz_offset",
}


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
        candidates = [
            directory / pattern.format(season=season, ext="csv.gz"),
            directory / pattern.format(season=season, ext="csv"),
        ]
        existing = [path for path in candidates if path.exists()]
        if len(existing) != 1:
            raise ValueError(f"NFL_FROZEN_SOURCE_FILE_COUNT:{season}:{pattern}:{len(existing)}")
        files.append(existing[0])
    return files


def _extend(target: list[dict[str, str]], paths: Iterable[Path], fields: set[str]) -> None:
    for path in paths:
        target.extend(_read_projected(path, fields))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedule-file", type=Path, required=True)
    parser.add_argument("--pbp-dir", type=Path, required=True)
    parser.add_argument("--participation-dir", type=Path, required=True)
    parser.add_argument("--depth-dir", type=Path, required=True)
    parser.add_argument("--stadium-file", type=Path, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--start-season", type=int, default=2016)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--min-train-seasons", type=int, default=2)
    parser.add_argument("--ridge-alpha", type=float, default=10.0)
    parser.add_argument("--neutral-site-policy", choices=("error", "exclude_from_evaluation"), default="exclude_from_evaluation")
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_production_validation.json"))
    parser.add_argument("--manifest-out", type=Path, default=Path("artifacts/football/nfl_source_manifest.json"))
    args = parser.parse_args()

    git_sha = str(args.git_sha).strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("NFL_PRODUCTION_GIT_SHA_INVALID")
    if args.end_season < args.start_season:
        raise SystemExit("END_SEASON_BEFORE_START_SEASON")
    if args.start_season < 2016:
        raise SystemExit("NFL_PRODUCTION_PRESSURE_HISTORY_STARTS_2016")

    pbp_files = _files(args.pbp_dir, "play_by_play_{season}.{ext}", args.start_season, args.end_season)
    participation_files = _files(args.participation_dir, "pbp_participation_{season}.{ext}", args.start_season, args.end_season)
    depth_files = _files(args.depth_dir, "depth_charts_{season}.{ext}", args.start_season, args.end_season)

    schedule_sha = _sha(args.schedule_file)
    sources = [
        {"name": "schedule", "uri": "frozen://nflverse/games.csv", "sha256": schedule_sha},
        {"name": "stadiums", "uri": "frozen://greerreNFL/Stadiums/team_stadiums.csv", "sha256": _sha(args.stadium_file)},
    ]
    for prefix, paths in (("pbp", pbp_files), ("participation", participation_files), ("depth", depth_files)):
        for path in paths:
            season = next(
                token for token in path.stem.replace(".csv", "").split("_")
                if token.isdigit() and len(token) == 4
            )
            sources.append({"name": f"{prefix}_{season}", "uri": f"frozen://nflverse/{path.name}", "sha256": _sha(path)})
    manifest = build_nfl_source_manifest(sources, schedule_anchor_sha256=schedule_sha)
    manifest_hash = manifest_sha256(manifest)
    manifest_payload = dict(manifest)
    manifest_payload["manifest_sha256"] = manifest_hash
    manifest_payload["participation_attribution"] = {
        "2016_2022": "NFL NextGenStats via nflverse",
        "2023_plus": "FTN Data via nflverse",
        "license": "CC-BY-SA-4.0 per nflverse participation release",
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    schedule_text = args.schedule_file.read_text(encoding="utf-8-sig")
    schedule = normalize_nfl_rows(parse_schedule_csv(schedule_text), range(args.start_season, args.end_season + 1))

    pbp: list[dict[str, str]] = []
    participation: list[dict[str, str]] = []
    depth: list[dict[str, str]] = []
    _extend(pbp, pbp_files, _PBP_FIELDS)
    _extend(participation, participation_files, _PARTICIPATION_FIELDS)
    _extend(depth, depth_files, _DEPTH_FIELDS)
    stadiums = _read_projected(args.stadium_file, _STADIUM_FIELDS)

    prior_curves = fit_nfl_prior_decay_curves(
        schedule,
        pbp,
        min_train_seasons=args.min_train_seasons,
        weeks=range(1, 7),
    )
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
        raise SystemExit("NFL_PRODUCTION_HISTORY_ROWS_EMPTY")

    evidence = build_production_nfl_validation_evidence(
        history_rows,
        source_uri=f"manifest://sha256/{manifest_hash}",
        source_sha256=manifest_hash,
        min_train_seasons=args.min_train_seasons,
        ridge_alpha=args.ridge_alpha,
    )
    evidence["code_git_sha"] = git_sha
    evidence["source_manifest_sha256"] = manifest_hash
    evidence["schedule_anchor_sha256"] = schedule_sha
    evidence["source_manifest_path"] = str(args.manifest_out)
    evidence["season_range"] = [args.start_season, args.end_season]
    evidence["point_in_time_history_row_count"] = len(history_rows)
    evidence["neutral_site_policy"] = args.neutral_site_policy

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "code_git_sha": git_sha,
        "model_id": evidence["model_id"],
        "feature_contract": evidence["feature_contract"],
        "source_manifest_sha256": manifest_hash,
        "history_rows": len(history_rows),
        "fold_count": evidence["fold_count"],
        "promotion_evidence": evidence["promotion_evidence"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
