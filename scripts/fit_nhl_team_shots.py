#!/usr/bin/env python3
from __future__ import annotations

"""Fit a versioned NHL matchup team-SOG development artifact."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from sportsedge.sports.nhl.official_boxscore_source import completed_game_from_json_dict
from sportsedge.sports.nhl.team_shot_history import fit_matchup_team_shot_parameters


def _load_games(path: Path):
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(completed_game_from_json_dict(json.loads(line)))
        except Exception as exc:
            raise ValueError(f"invalid completed-game row {line_number}: {exc}") from exc
    return tuple(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Fit SportsEdge NHL team-SOG matchup development parameters")
    parser.add_argument("--completed-games", required=True, type=Path)
    parser.add_argument("--home-team-id", required=True)
    parser.add_argument("--away-team-id", required=True)
    parser.add_argument("--cutoff", required=True, help="Timezone-aware target cutoff")
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--min-games", type=int, default=10)
    parser.add_argument("--shrinkage-games", type=float, default=10.0)
    args = parser.parse_args()

    fit = fit_matchup_team_shot_parameters(
        _load_games(args.completed_games),
        home_team_id=args.home_team_id,
        away_team_id=args.away_team_id,
        cutoff=args.cutoff,
        version=args.version,
        min_games=args.min_games,
        shrinkage_games=args.shrinkage_games,
    )
    payload = asdict(fit)
    payload["parameters"] = asdict(fit.parameters)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
