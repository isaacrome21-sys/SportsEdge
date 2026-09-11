from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

from .mlb_v7_travel_history import (
    HistoricalGameRow,
    MLBV7TravelHistoryError,
    VenueReferenceRow,
    _get_json,
    extract_timecodes,
    historical_snapshot_url,
    normalize_final_game,
    parse_venue_reference,
    schedule_games,
    schedule_url,
    timestamps_url,
    venue_url,
    write_json,
    write_jsonl,
)

MAX_SLICE_DAYS = 31


def _date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise MLBV7TravelHistoryError(f"{field}_INVALID") from exc


def collect_history_slice(
    start_date: str,
    end_date: str,
    output_dir: Path,
    *,
    opener: Callable = urlopen,
    retrieved_at: datetime | None = None,
    max_days: int = MAX_SLICE_DAYS,
) -> dict[str, Any]:
    """Collect hash-bound normalized MLB travel evidence for one bounded date slice.

    This is deliberately not an attestation writer. Full 2023-2025 coverage and
    downstream decision-time binding remain separate requirements before source
    readiness can be asserted.
    """
    start = _date(start_date, "START_DATE")
    end = _date(end_date, "END_DATE")
    if end < start:
        raise MLBV7TravelHistoryError("DATE_RANGE_REVERSED")
    if (end - start).days + 1 > int(max_days):
        raise MLBV7TravelHistoryError("DATE_RANGE_EXCEEDS_MAX_DAYS")
    now = retrieved_at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise MLBV7TravelHistoryError("RETRIEVED_AT_NOT_TIMEZONE_AWARE")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    history_rows: list[HistoricalGameRow] = []
    venues: dict[int, VenueReferenceRow] = {}
    failures: list[dict[str, Any]] = []

    games = schedule_games(_get_json(schedule_url(start_date, end_date), opener))
    status_counts: dict[str, int] = {}
    for game in games:
        status = str(game["status"])
        status_counts[status] = status_counts.get(status, 0) + 1
        if status != "Final":
            failures.append({
                "game_id": game["game_id"],
                "stage": "SCHEDULE_STATUS",
                "reason": f"HISTORICAL_GAME_NOT_FINAL:{status}",
            })
            continue
        try:
            timecodes_payload = _get_json(timestamps_url(game["game_id"]), opener)
            timecodes = extract_timecodes(timecodes_payload)
            final_snapshot = _get_json(historical_snapshot_url(game["game_id"], timecodes[-1]), opener)
            history_rows.extend(normalize_final_game(game, timecodes_payload, final_snapshot))
            venue_id = int(game["venue_id"])
            if venue_id not in venues:
                venues[venue_id] = parse_venue_reference(_get_json(venue_url(venue_id), opener), venue_id)
        except MLBV7TravelHistoryError as exc:
            failures.append({"game_id": game["game_id"], "stage": "GAME_EVIDENCE", "reason": str(exc)})

    history_rows.sort(key=lambda row: (row.game_start_time, row.game_id, row.side))
    venue_rows = [venues[key] for key in sorted(venues)]
    history_path = output_dir / "mlb_statsapi_history.jsonl"
    venue_path = output_dir / "venue_reference.jsonl"
    history_sha = write_jsonl(history_path, history_rows)
    venue_sha = write_jsonl(venue_path, venue_rows)

    fully_verified = not failures and len(history_rows) == 2 * len(games)
    blockers = ["FULL_2023_2025_COVERAGE_NOT_COLLECTED", "DECISION_TIME_BINDING_NOT_ATTESTED"]
    if failures:
        blockers.insert(0, "SLICE_SOURCE_INCOMPLETE")
    report = {
        "contract": "SPORTSEDGE_MLB_V7_TRAVEL_HISTORY_SOURCE_SLICE_V1",
        "state": "PASS_SOURCE_SLICE" if fully_verified else "BLOCKED_SOURCE_SLICE",
        "coverage_start": start_date,
        "coverage_end": end_date,
        "retrieved_at": now.astimezone(timezone.utc).isoformat(),
        "schedule_game_count": len(games),
        "status_counts": status_counts,
        "verified_game_count": len(history_rows) // 2,
        "team_row_count": len(history_rows),
        "venue_count": len(venue_rows),
        "failures": failures,
        "evidence": {
            "mlb_statsapi_history": {"path": history_path.name, "sha256": history_sha},
            "venue_reference": {"path": venue_path.name, "sha256": venue_sha},
        },
        "final_at_semantics": "LAST_HISTORICAL_TIMECODE_CONFIRMED_FINAL_UPPER_BOUND",
        "promotion_authority": False,
        "candidate_training_allowed": False,
        "attestation_written": False,
        "source_readiness_authority": False,
        "blockers": blockers,
    }
    write_json(output_dir / "source_slice_report.json", report)
    return report
