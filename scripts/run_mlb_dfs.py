#!/usr/bin/env python3
"""Build a SportsEdge MLB DFS portfolio from JSON projections.

Input JSON: a list of player objects matching PlayerProjection fields.
Output JSON: legal lineups plus correlated Monte Carlo metrics.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.dfs_mlb import DFSConfig, PlayerProjection, build_portfolio


def _load_players(path: Path) -> list[PlayerProjection]:
    raw = json.loads(path.read_text())
    players: list[PlayerProjection] = []
    for row in raw:
        players.append(
            PlayerProjection(
                player_id=str(row["player_id"]),
                name=str(row["name"]),
                team=str(row["team"]),
                opponent=str(row["opponent"]),
                positions=tuple(row["positions"]),
                salary=int(row["salary"]),
                projection=float(row["projection"]),
                stdev=float(row["stdev"]),
                ownership=float(row.get("ownership", 0.0)),
                batting_order=(None if row.get("batting_order") is None else int(row["batting_order"])),
                is_pitcher=bool(row.get("is_pitcher", False)),
                game_id=row.get("game_id"),
            )
        )
    return players


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, default=Path("mlb_dfs_card.json"))
    parser.add_argument("--lineups", type=int, default=20)
    parser.add_argument("--sims", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20260815)
    parser.add_argument("--min-salary", type=int, default=0)
    parser.add_argument("--max-exposure", type=float, default=0.70)
    parser.add_argument("--min-unique", type=int, default=2)
    args = parser.parse_args()

    cfg = DFSConfig(
        max_lineups=args.lineups,
        min_salary=args.min_salary,
        max_player_exposure=args.max_exposure,
        min_unique_players=args.min_unique,
    )
    portfolio = build_portfolio(_load_players(args.input), cfg, seed=args.seed, n_sims=args.sims)

    simulation_by_ids = {
        tuple(p.player_id for p in result.lineup.players): result for result in portfolio.simulation
    }
    output = []
    for lineup in portfolio.lineups:
        key = tuple(p.player_id for p in lineup.players)
        sim = simulation_by_ids.get(key)
        output.append(
            {
                "salary": lineup.salary,
                "projection": lineup.projection,
                "ownership_sum": lineup.ownership_sum,
                "players": [
                    {
                        "slot": slot,
                        "player_id": player.player_id,
                        "name": player.name,
                        "team": player.team,
                        "salary": player.salary,
                        "projection": player.projection,
                        "ownership": player.ownership,
                    }
                    for slot, player in zip(lineup.slots, lineup.players)
                ],
                "monte_carlo": None
                if sim is None
                else {
                    "mean": sim.mean,
                    "median": sim.median,
                    "p90": sim.p90,
                    "p95": sim.p95,
                    "boom_rate": sim.boom_rate,
                    "top_lineup_rate": sim.top_lineup_rate,
                },
            }
        )

    args.output.write_text(json.dumps(output, indent=2))
    print(f"wrote {len(output)} lineups to {args.output}")


if __name__ == "__main__":
    main()
