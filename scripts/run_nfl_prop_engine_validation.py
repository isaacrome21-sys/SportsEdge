#!/usr/bin/env python3
"""Run exact-source NFL player-prop engine walk-forward diagnostics."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.nfl.computed_prop_trends import fetch_nfl_prop_trend_inputs
from sportsedge.sports.nfl.prop_engine_validation import build_nfl_prop_walkforward_evidence

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _manifest_hash(*, player_sources, schedule_sha256: str) -> str:
    payload = {
        "contract": "NFL_PROP_ENGINE_SOURCE_MANIFEST_V1",
        "player_sources": [
            {
                "season": int(source.season),
                "source_uri": source.source_uri,
                "source_sha256": source.source_sha256,
            }
            for source in sorted(player_sources, key=lambda item: int(item.season))
        ],
        "schedule_sha256": str(schedule_sha256).lower(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _schedule_index(schedule_rows):
    out = {}
    for row in schedule_rows:
        game_id = str(row.get("game_id") or "").strip()
        if not game_id:
            continue
        if game_id in out:
            raise SystemExit(f"NFL_PROP_VALIDATION_DUPLICATE_SCHEDULE_GAME:{game_id}")
        out[game_id] = row
    return out


def _kickoff_iso(row):
    from sportsedge.sports.nfl.auto_context_source import _kickoff
    return _kickoff(row).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=2021)
    parser.add_argument("--end-season", type=int, default=2025)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--min-games", type=int, default=6)
    parser.add_argument("--out", type=Path, default=Path("artifacts/football/nfl_prop_engine_validation.json"))
    parser.add_argument("--manifest-out", type=Path, default=Path("artifacts/football/nfl_prop_engine_source_manifest.json"))
    args = parser.parse_args()

    git_sha = str(args.git_sha or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("NFL_PROP_VALIDATION_GIT_SHA_INVALID")
    if args.start_season < 1999 or args.end_season < args.start_season:
        raise SystemExit("NFL_PROP_VALIDATION_SEASON_RANGE_INVALID")
    if args.min_games < 2:
        raise SystemExit("NFL_PROP_VALIDATION_MIN_GAMES_INVALID")

    seasons = list(range(args.start_season, args.end_season + 1))
    player, schedule_rows, schedule_sha = fetch_nfl_prop_trend_inputs(seasons=seasons)
    schedule = _schedule_index(schedule_rows)

    rows = []
    missing_schedule = 0
    for raw in player.rows:
        row = dict(raw)
        try:
            season = int(float(row.get("season")))
        except (TypeError, ValueError):
            continue
        if season not in seasons or str(row.get("season_type") or "").upper() != "REG":
            continue
        game_id = str(row.get("game_id") or "").strip()
        schedule_row = schedule.get(game_id)
        if schedule_row is None:
            missing_schedule += 1
            continue
        row["kickoff_ts"] = _kickoff_iso(schedule_row)
        rows.append(row)

    if not rows:
        raise SystemExit("NFL_PROP_VALIDATION_PLAYER_ROWS_EMPTY")

    manifest_payload = {
        "contract": "NFL_PROP_ENGINE_SOURCE_MANIFEST_V1",
        "code_git_sha": git_sha,
        "season_range": [args.start_season, args.end_season],
        "schedule_sha256": schedule_sha,
        "player_sources": [
            {
                "season": int(source.season),
                "source_uri": source.source_uri,
                "source_sha256": source.source_sha256,
            }
            for source in sorted(player.sources, key=lambda item: int(item.season))
        ],
        "raw_player_row_count": len(player.rows),
        "eligible_regular_season_row_count": len(rows),
        "missing_schedule_row_count": missing_schedule,
    }
    manifest_sha = _manifest_hash(player_sources=player.sources, schedule_sha256=schedule_sha)
    manifest_payload["manifest_sha256"] = manifest_sha

    evidence = build_nfl_prop_walkforward_evidence(
        rows,
        source_manifest_sha256=manifest_sha,
        min_games=args.min_games,
    )
    evidence.update({
        "code_git_sha": git_sha,
        "season_range": [args.start_season, args.end_season],
        "source_manifest_sha256": manifest_sha,
        "source_manifest_path": str(args.manifest_out),
        "raw_player_row_count": len(player.rows),
        "eligible_regular_season_row_count": len(rows),
        "missing_schedule_row_count": missing_schedule,
        "production_registry_consumes_this_artifact": False,
        "promotion_authority": False,
    })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": evidence["status"],
        "evaluation_count": evidence["evaluation_count"],
        "player_count": evidence["player_count"],
        "manifest_sha256": manifest_sha,
        "promotion_eligible": False,
        "promotion_authority": False,
        "production_registry_consumes_this_artifact": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
