"""Player-market read-outs from the shared Engine-A/Engine-B ensemble.

No player market gets its own simulation. Every sample is derived from the exact
same ordered game path and its identity-bound participation overlay.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from .drive_play import FootballPlayPath
from .participation import ParticipationEvent, aggregate_player_box_scores, validate_participation


_BOX_MARKETS = {
    "passing_yards": "passing_yards",
    "completions": "completions",
    "attempts": "pass_attempts",
    "passing_tds": "passing_tds",
    "interceptions": "interceptions_thrown",
    "rush_yards": "rushing_yards",
    "longest_completion": "longest_completion",
    "rushing_yards": "rushing_yards",
    "receiving_yards": "receiving_yards",
    "receptions": "receptions",
    "rush_attempts": "rush_attempts",
    "targets": "targets",
    "longest_reception": "longest_reception",
    "longest_rush": "longest_rush",
}


def _price(samples: list[float], line: float) -> dict[str, float]:
    if not samples:
        raise ValueError("PLAYER_MARKET_SAMPLES_REQUIRED")
    n = float(len(samples))
    return {
        "over": sum(value > line for value in samples) / n,
        "under": sum(value < line for value in samples) / n,
        "push": sum(value == line for value in samples) / n,
    }


def _first_td_scorer(path: FootballPlayPath, overlay: tuple[ParticipationEvent, ...]) -> str | None:
    by_play = {part.play_id: part for part in overlay}
    for play in path.plays:
        if play.points != 7:
            continue
        part = by_play[play.play_id]
        if play.play_type == "PASS":
            if play.pass_complete is not True or not part.receiver_id:
                raise ValueError("FIRST_TD_PASS_SCORER_UNRESOLVED")
            return part.receiver_id
        if play.play_type == "RUSH":
            if not part.rusher_id:
                raise ValueError("FIRST_TD_RUSH_SCORER_UNRESOLVED")
            return part.rusher_id
        raise ValueError(f"FIRST_TD_PLAY_TYPE_UNSUPPORTED:{play.play_type}")
    return None


def derive_player_market_readouts(
    paths: Iterable[FootballPlayPath],
    overlays: Iterable[Iterable[ParticipationEvent]],
    *,
    lines: Mapping[str, Mapping[str, float]] | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    path_rows = list(paths)
    overlay_rows = [tuple(row) for row in overlays]
    if not path_rows:
        raise ValueError("ENGINE_A_PATHS_REQUIRED")
    if len(path_rows) != len(overlay_rows):
        raise ValueError("PARTICIPATION_ENSEMBLE_COUNT_MISMATCH")

    game_ids = {path.game_id for path in path_rows}
    teams = {(path.home_team, path.away_team) for path in path_rows}
    if len(game_ids) != 1 or len(teams) != 1:
        raise ValueError("PARTICIPATION_ENSEMBLE_IDENTITY_MISMATCH")

    boxes_by_sim: list[dict[tuple[str, str], object]] = []
    player_ids: set[str] = set()
    first_td_counts: Counter[str] = Counter()
    for path, overlay in zip(path_rows, overlay_rows):
        validate_participation(path, overlay)
        boxes = aggregate_player_box_scores(path, overlay)
        boxes_by_sim.append(boxes)
        player_ids.update(player_id for _, player_id in boxes)
        for part in overlay:
            for player_id in (part.quarterback_id, part.rusher_id, part.target_id, part.receiver_id):
                if player_id:
                    player_ids.add(player_id)
        scorer = _first_td_scorer(path, overlay)
        if scorer is not None:
            first_td_counts[scorer] += 1

    n = float(len(path_rows))
    market_lines = {str(market): dict(player_lines) for market, player_lines in (lines or {}).items()}
    unknown_line_markets = set(market_lines) - (set(_BOX_MARKETS) | {"pass_plus_rush_yards", "rush_plus_rec_yards"})
    if unknown_line_markets:
        raise ValueError(f"PLAYER_MARKET_LINE_UNSUPPORTED:{sorted(unknown_line_markets)[0]}")

    # Map player id to its team using any box/participation occurrence. Player ids
    # are required to be globally stable within the game; collision across teams
    # fails closed.
    player_team: dict[str, str] = {}
    for boxes in boxes_by_sim:
        for team, player_id in boxes:
            prior = player_team.setdefault(player_id, team)
            if prior != team:
                raise ValueError(f"PLAYER_ID_TEAM_COLLISION:{player_id}")
    for path, overlay in zip(path_rows, overlay_rows):
        by_play = {play.play_id: play for play in path.plays}
        for part in overlay:
            team = by_play[part.play_id].possession
            for player_id in (part.quarterback_id, part.rusher_id, part.target_id, part.receiver_id):
                if player_id:
                    prior = player_team.setdefault(player_id, team)
                    if prior != team:
                        raise ValueError(f"PLAYER_ID_TEAM_COLLISION:{player_id}")

    readout: dict[str, dict[str, dict[str, object]]] = {market: {} for market in _BOX_MARKETS}
    readout["pass_plus_rush_yards"] = {}
    readout["rush_plus_rec_yards"] = {}
    readout["anytime_td"] = {}
    readout["first_td"] = {}
    readout["two_plus_td"] = {}

    def box_for(index: int, player_id: str):
        team = player_team[player_id]
        return boxes_by_sim[index].get((team, player_id))

    for player_id in sorted(player_ids):
        for market, attribute in _BOX_MARKETS.items():
            samples = [
                float(getattr(box, attribute)) if (box := box_for(index, player_id)) is not None else 0.0
                for index in range(len(path_rows))
            ]
            row: dict[str, object] = {"samples": tuple(samples), "mean": sum(samples) / n}
            if player_id in market_lines.get(market, {}):
                row["price"] = _price(samples, float(market_lines[market][player_id]))
            readout[market][player_id] = row

        pass_rush = []
        rush_rec = []
        td_samples = []
        for index in range(len(path_rows)):
            box = box_for(index, player_id)
            if box is None:
                pass_rush.append(0.0)
                rush_rec.append(0.0)
                td_samples.append(0.0)
            else:
                pass_rush.append(float(box.passing_yards + box.rushing_yards))
                rush_rec.append(float(box.rushing_yards + box.receiving_yards))
                td_samples.append(float(box.rushing_tds + box.receiving_tds))

        for market, samples in (
            ("pass_plus_rush_yards", pass_rush),
            ("rush_plus_rec_yards", rush_rec),
        ):
            row = {"samples": tuple(samples), "mean": sum(samples) / n}
            if player_id in market_lines.get(market, {}):
                row["price"] = _price(samples, float(market_lines[market][player_id]))
            readout[market][player_id] = row

        readout["anytime_td"][player_id] = {
            "samples": tuple(td_samples),
            "probability": sum(value >= 1.0 for value in td_samples) / n,
        }
        readout["two_plus_td"][player_id] = {
            "samples": tuple(td_samples),
            "probability": sum(value >= 2.0 for value in td_samples) / n,
        }
        readout["first_td"][player_id] = {
            "probability": first_td_counts.get(player_id, 0) / n,
        }

    return readout
