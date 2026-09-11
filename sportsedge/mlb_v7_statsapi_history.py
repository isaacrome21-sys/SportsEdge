from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from .mlb_v7_travel_history import HistoricalGameRow

SOURCE_CLASS = "MLB_STATSAPI_HISTORY"
REQUIRED_FIELDS = ["game_id", "team_id", "venue_id", "game_start_time", "status", "final_at"]
REQUIRED_SEMANTICS = {
    "point_in_time": True,
    "final_before_decision": True,
    "complete_schedule_chain": True,
}
TERMINAL_NONPLAYED_DETAILED_STATUSES = {"Cancelled", "Postponed"}


class MLBV7StatsAPIHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScheduleDisposition:
    game_id: int
    official_date: str
    status: str
    disposition: str
    reason: str | None


def month_windows(start: date, end: date) -> list[tuple[date, date]]:
    if start > end:
        raise MLBV7StatsAPIHistoryError("COVERAGE_INVALID")
    out: list[tuple[date, date]] = []
    cursor = date(start.year, start.month, 1)
    while cursor <= end:
        next_month = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)
        left = max(start, cursor)
        right = min(end, next_month - timedelta(days=1))
        out.append((left, right))
        cursor = next_month
    return out


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, value: Any) -> str:
    data = canonical_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def write_jsonl(path: Path, rows: Iterable[Any]) -> str:
    data = b"".join(canonical_bytes(asdict(row) if hasattr(row, "__dataclass_fields__") else row) for row in rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def detailed_status_by_game(payload: Any) -> dict[int, str]:
    if not isinstance(payload, dict):
        raise MLBV7StatsAPIHistoryError("SCHEDULE_PAYLOAD_INVALID")
    out: dict[int, str] = {}
    for date_block in payload.get("dates") or []:
        for game in date_block.get("games") or []:
            try:
                game_id = int(game["gamePk"])
            except Exception as exc:
                raise MLBV7StatsAPIHistoryError("SCHEDULE_GAME_IDENTITY_INCOMPLETE") from exc
            detailed = str((game.get("status") or {}).get("detailedState") or "")
            if not detailed:
                raise MLBV7StatsAPIHistoryError(f"SCHEDULE_DETAILED_STATUS_MISSING:{game_id}")
            out[game_id] = detailed
    return out


def classify_schedule_games(games: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[ScheduleDisposition]]:
    finals: list[dict[str, Any]] = []
    dispositions: list[ScheduleDisposition] = []
    for game in games:
        status = str(game.get("status") or "")
        detailed = str(game.get("detailed_status") or "")
        game_id = int(game["game_id"])
        official_date = str(game["official_date"])
        if status == "Final":
            finals.append(game)
            dispositions.append(ScheduleDisposition(game_id, official_date, status, "ACQUIRE_FINAL", None))
        elif detailed in TERMINAL_NONPLAYED_DETAILED_STATUSES:
            dispositions.append(ScheduleDisposition(
                game_id, official_date, status, "EXCLUDED_TERMINAL_NONPLAYED", detailed,
            ))
        else:
            dispositions.append(ScheduleDisposition(
                game_id, official_date, status, "BLOCKED_NONFINAL",
                detailed or f"HISTORICAL_SCHEDULE_STATUS_{status or 'MISSING'}",
            ))
    return finals, dispositions


def build_shard_report(
    *,
    coverage_start: str,
    coverage_end: str,
    games: list[dict[str, Any]],
    normalized_rows: list[HistoricalGameRow],
    failures: list[dict[str, Any]],
    evidence_files: list[dict[str, str]],
) -> dict[str, Any]:
    finals, dispositions = classify_schedule_games(games)
    acquired_games = {row.game_id for row in normalized_rows}
    duplicate_team_keys = len({(row.game_id, row.team_id) for row in normalized_rows}) != len(normalized_rows)
    final_ids = {int(game["game_id"]) for game in finals}
    missing_final_ids = sorted(final_ids - acquired_games)
    extra_game_ids = sorted(acquired_games - final_ids)
    bad_row_counts = sorted(
        game_id for game_id in acquired_games
        if sum(1 for row in normalized_rows if row.game_id == game_id) != 2
    )
    blocked_nonfinal = sorted(
        item.game_id for item in dispositions if item.disposition == "BLOCKED_NONFINAL"
    )
    ready = not failures and not duplicate_team_keys and not missing_final_ids and not extra_game_ids and not bad_row_counts and not blocked_nonfinal
    blockers: list[str] = []
    if failures:
        blockers.append("GAME_ACQUISITION_FAILURES")
    if duplicate_team_keys:
        blockers.append("DUPLICATE_TEAM_ROWS")
    if missing_final_ids:
        blockers.append("FINAL_GAMES_MISSING")
    if extra_game_ids:
        blockers.append("UNSCHEDULED_NORMALIZED_GAMES")
    if bad_row_counts:
        blockers.append("FINAL_GAME_TEAM_ROW_COUNT_INVALID")
    if blocked_nonfinal:
        blockers.append("HISTORICAL_SCHEDULE_NONFINAL_UNRESOLVED")
    return {
        "contract": "SPORTSEDGE_MLB_V7_STATSAPI_HISTORY_SHARD_V1",
        "source_class": SOURCE_CLASS,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "schedule_game_count": len(games),
        "scheduled_final_game_count": len(finals),
        "normalized_final_game_count": len(acquired_games),
        "normalized_team_row_count": len(normalized_rows),
        "schedule_dispositions": [asdict(x) for x in dispositions],
        "missing_final_game_ids": missing_final_ids,
        "extra_game_ids": extra_game_ids,
        "bad_team_row_count_game_ids": bad_row_counts,
        "blocked_nonfinal_game_ids": blocked_nonfinal,
        "failures": failures,
        "evidence_files": evidence_files,
        "state": "SHARD_READY" if ready else "SHARD_BLOCKED",
        "promotion_authority": False,
        "candidate_training_allowed": False,
        "attestation_authority": False,
        "blockers": blockers,
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception as exc:
        raise MLBV7StatsAPIHistoryError(f"INVALID_JSON:{path}") from exc


def _safe(root: Path, relative: str) -> Path:
    base = root.resolve()
    candidate = (base / relative).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as exc:
        raise MLBV7StatsAPIHistoryError(f"PATH_ESCAPES_ROOT:{relative}") from exc
    return candidate


def _verify_evidence_files(root: Path, evidence_files: Any) -> None:
    if not isinstance(evidence_files, list) or not evidence_files:
        raise MLBV7StatsAPIHistoryError("SHARD_EVIDENCE_FILES_MISSING")
    for item in evidence_files:
        if not isinstance(item, Mapping):
            raise MLBV7StatsAPIHistoryError("SHARD_EVIDENCE_ENTRY_INVALID")
        rel = item.get("path")
        expected = item.get("sha256")
        if not isinstance(rel, str) or not isinstance(expected, str) or len(expected) != 64:
            raise MLBV7StatsAPIHistoryError("SHARD_EVIDENCE_ENTRY_INVALID")
        path = _safe(root, rel)
        if not path.is_file():
            raise MLBV7StatsAPIHistoryError(f"SHARD_EVIDENCE_MISSING:{rel}")
        if sha256_file(path) != expected.lower():
            raise MLBV7StatsAPIHistoryError(f"SHARD_EVIDENCE_SHA_MISMATCH:{rel}")


def finalize_history(
    *,
    shard_root: Path,
    coverage_start: str,
    coverage_end: str,
    output_root: Path,
) -> dict[str, Any]:
    start = date.fromisoformat(coverage_start)
    end = date.fromisoformat(coverage_end)
    windows = month_windows(start, end)
    all_rows: list[dict[str, Any]] = []
    shard_receipts: list[dict[str, Any]] = []
    seen_games: set[int] = set()
    blockers: list[str] = []

    for left, right in windows:
        label = left.strftime("%Y-%m")
        shard_dir = shard_root / label
        report_path = shard_dir / "shard_report.json"
        rows_path = shard_dir / "normalized" / "MLB_STATSAPI_HISTORY.jsonl"
        if not report_path.is_file() or not rows_path.is_file():
            blockers.append(f"SHARD_MISSING:{label}")
            continue
        report = _load_json(report_path)
        if report.get("state") != "SHARD_READY":
            blockers.append(f"SHARD_NOT_READY:{label}")
            continue
        if report.get("coverage_start") != left.isoformat() or report.get("coverage_end") != right.isoformat():
            blockers.append(f"SHARD_COVERAGE_MISMATCH:{label}")
            continue
        try:
            _verify_evidence_files(shard_dir, report.get("evidence_files"))
        except MLBV7StatsAPIHistoryError as exc:
            blockers.append(f"{label}:{exc}")
            continue
        rows: list[dict[str, Any]] = []
        for lineno, raw in enumerate(rows_path.read_text().splitlines(), start=1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise MLBV7StatsAPIHistoryError(f"ROW_INVALID:{label}:{lineno}")
            rows.append(value)
        game_counts: dict[int, int] = {}
        for row in rows:
            game_id = int(row["game_id"])
            game_counts[game_id] = game_counts.get(game_id, 0) + 1
        if any(count != 2 for count in game_counts.values()):
            blockers.append(f"SHARD_TEAM_ROW_COUNT_INVALID:{label}")
            continue
        overlap = sorted(set(game_counts) & seen_games)
        if overlap:
            blockers.append(f"SHARD_GAME_OVERLAP:{label}:{overlap[0]}")
            continue
        seen_games.update(game_counts)
        all_rows.extend(rows)
        shard_receipts.append({
            "label": label,
            "coverage_start": left.isoformat(),
            "coverage_end": right.isoformat(),
            "report_sha256": sha256_file(report_path),
            "rows_sha256": sha256_file(rows_path),
            "final_game_count": len(game_counts),
            "team_row_count": len(rows),
        })

    state = "READY_TO_ATTEST" if not blockers and len(shard_receipts) == len(windows) else "BLOCKED_INCOMPLETE_HISTORY"
    result: dict[str, Any] = {
        "contract": "SPORTSEDGE_MLB_V7_STATSAPI_HISTORY_FINALIZE_V1",
        "source_class": SOURCE_CLASS,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "required_shard_count": len(windows),
        "verified_shard_count": len(shard_receipts),
        "final_game_count": len(seen_games),
        "team_row_count": len(all_rows),
        "state": state,
        "blockers": blockers,
        "promotion_authority": False,
        "candidate_training_allowed": False,
        "attestation_written": False,
    }
    output_root.mkdir(parents=True, exist_ok=True)
    if state != "READY_TO_ATTEST":
        write_json(output_root / "finalize_report.json", result)
        return result

    all_rows.sort(key=lambda row: (str(row["game_start_time"]), int(row["game_id"]), int(row["team_id"])))
    evidence_rel = Path("raw") / "MLB_STATSAPI_HISTORY.jsonl"
    receipts_rel = Path("raw") / "MLB_STATSAPI_HISTORY_SHARDS.json"
    evidence_sha = write_jsonl(output_root / evidence_rel, all_rows)
    receipts_sha = write_json(output_root / receipts_rel, shard_receipts)
    evidence_files = [
        {"path": evidence_rel.as_posix(), "sha256": evidence_sha},
        {"path": receipts_rel.as_posix(), "sha256": receipts_sha},
    ]
    attestation = {
        "source_class": SOURCE_CLASS,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "fields": REQUIRED_FIELDS,
        "semantics": REQUIRED_SEMANTICS,
        "evidence_files": evidence_files,
    }
    write_json(output_root / "attestations" / f"{SOURCE_CLASS}.json", attestation)
    result.update({
        "attestation_written": True,
        "evidence_files": evidence_files,
        "attestation_sha256": sha256_file(output_root / "attestations" / f"{SOURCE_CLASS}.json"),
    })
    write_json(output_root / "finalize_report.json", result)
    return result
