"""Deterministic market-blind PBP -> ordered V2K drive rows for attempt 0."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from .v2k_drive_core import DriveRow, normalize_drive_rows

_OUTCOME_MAP = {
    "touchdown": "TD", "td": "TD",
    "field_goal": "FG", "field goal": "FG", "fg": "FG",
    "interception": "TURNOVER", "fumble": "TURNOVER",
    "turnover_on_downs": "TURNOVER", "turnover on downs": "TURNOVER",
    "punt": "PUNT_OTHER", "end_of_half": "PUNT_OTHER", "end of half": "PUNT_OTHER",
    "end_of_game": "PUNT_OTHER", "end of game": "PUNT_OTHER",
    "missed_field_goal": "PUNT_OTHER", "missed field goal": "PUNT_OTHER",
    "safety": "SAFETY",
    "defensive_touchdown": "DEF_ST_SCORE", "defensive touchdown": "DEF_ST_SCORE",
    "special_teams_touchdown": "DEF_ST_SCORE", "special teams touchdown": "DEF_ST_SCORE",
}

_TERMINATION_MAP = {
    "end_of_half": "END_OF_HALF", "end of half": "END_OF_HALF",
    "end_of_game": "END_OF_GAME", "end of game": "END_OF_GAME",
}

_REQUIRED = {
    "game_id", "season", "week", "kickoff_utc", "drive_id", "play_index",
    "offense", "defense", "start_yardline_100", "drive_result",
    "offense_score_before", "defense_score_before", "offense_score_after",
    "defense_score_after", "period", "clock_seconds_remaining_period",
}

_FORBIDDEN_MARKET_KEYS = {
    "spread", "closing_spread", "total", "closing_total", "moneyline",
    "home_odds", "away_odds", "implied_probability", "market_probability",
}


def _canonical_outcome(value: object) -> str:
    key = str(value or "").strip().lower()
    if key not in _OUTCOME_MAP:
        raise ValueError("V2K_DRIVE_OUTCOME_UNMAPPED")
    return _OUTCOME_MAP[key]


def _termination_reason(value: object) -> str:
    return _TERMINATION_MAP.get(str(value or "").strip().lower(), "NORMAL")


def _validate_game_chronology(rows: list[DriveRow]) -> None:
    if not rows:
        return
    season_week_kickoff = {(r.season, r.week, r.kickoff_utc) for r in rows}
    if len(season_week_kickoff) != 1:
        raise ValueError("V2K_GAME_IDENTITY_INCONSISTENT")
    previous: DriveRow | None = None
    end_game_seen = False
    for row in rows:
        if end_game_seen:
            raise ValueError("V2K_DRIVE_AFTER_END_OF_GAME")
        if row.period > 5:
            raise ValueError("V2K_PERIOD_UNSUPPORTED")
        clock_max = 600 if row.period == 5 else 900
        if row.clock_seconds_remaining_period > clock_max:
            raise ValueError("V2K_CLOCK_STATE_INVALID")
        if previous is not None:
            if row.period < previous.period:
                raise ValueError("V2K_PERIOD_REGRESSION")
            if row.period == previous.period and row.clock_seconds_remaining_period > previous.clock_seconds_remaining_period:
                raise ValueError("V2K_CLOCK_REGRESSION")
        if row.termination_reason == "END_OF_HALF" and row.period not in (2,):
            raise ValueError("V2K_END_OF_HALF_PERIOD_INVALID")
        if row.termination_reason == "END_OF_GAME":
            end_game_seen = True
        previous = row


def build_drive_rows_from_pbp(
    records: Iterable[Mapping[str, object]],
    *,
    source_manifest_sha256: str,
    source_code_sha: str,
) -> tuple[DriveRow, ...]:
    """Collapse ordered play records into one fail-closed row per drive."""
    if not source_manifest_sha256 or not source_code_sha:
        raise ValueError("V2K_SOURCE_BINDING_REQUIRED")

    grouped: dict[tuple[str, object], list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        if _FORBIDDEN_MARKET_KEYS.intersection(record):
            raise ValueError("V2K_MARKET_FIELD_FORBIDDEN")
        missing = sorted(k for k in _REQUIRED if k not in record or record[k] is None)
        if missing:
            raise ValueError("V2K_REQUIRED_PBP_FIELD_MISSING:" + ",".join(missing))
        grouped[(str(record["game_id"]), record["drive_id"])].append(record)

    by_game: dict[str, list[tuple[int, DriveRow]]] = defaultdict(list)
    for (game_id, _drive_id), plays in grouped.items():
        ordered = sorted(plays, key=lambda p: int(p["play_index"]))
        indexes = [int(p["play_index"]) for p in ordered]
        if len(indexes) != len(set(indexes)):
            raise ValueError("V2K_PLAY_INDEX_DUPLICATE")
        first, last = ordered[0], ordered[-1]
        offense = str(first["offense"])
        defense = str(first["defense"])
        if any(str(p["offense"]) != offense or str(p["defense"]) != defense for p in ordered):
            raise ValueError("V2K_DRIVE_TEAM_IDENTITY_CHANGED")
        outcome = _canonical_outcome(last["drive_result"])
        termination_reason = _termination_reason(last["drive_result"])
        conversion_points = int(last.get("conversion_points") or 0)
        drive_order = int(first.get("drive_order") if first.get("drive_order") is not None else min(indexes))
        row = DriveRow(
            game_id=game_id,
            season=int(first["season"]), week=int(first["week"]), kickoff_utc=str(first["kickoff_utc"]),
            drive_index=0, offense=offense, defense=defense,
            start_yardline_100=float(first["start_yardline_100"]), outcome=outcome,
            offense_score_before=int(first["offense_score_before"]), defense_score_before=int(first["defense_score_before"]),
            offense_score_after=int(last["offense_score_after"]), defense_score_after=int(last["defense_score_after"]),
            period=int(first["period"]), clock_seconds_remaining_period=int(first["clock_seconds_remaining_period"]),
            conversion_points=conversion_points, termination_reason=termination_reason,
            source_manifest_sha256=source_manifest_sha256, source_code_sha=source_code_sha,
        )
        by_game[game_id].append((drive_order, row))

    rows: list[DriveRow] = []
    for game_id in sorted(by_game):
        ordered_drives = sorted(by_game[game_id], key=lambda item: item[0])
        if len({order for order, _ in ordered_drives}) != len(ordered_drives):
            raise ValueError("V2K_DRIVE_ORDER_DUPLICATE")
        normalized_game = [DriveRow(**{**row.__dict__, "drive_index": idx}) for idx, (_order, row) in enumerate(ordered_drives)]
        _validate_game_chronology(normalized_game)
        rows.extend(normalized_game)
    return normalize_drive_rows(rows)


AUTHORITY = {
    "model_p": False, "pricing": False, "promotion": False, "staking": False,
    "run_it": False, "official": False, "untouched_readout": False,
    "development_validation_scoring": False,
}
