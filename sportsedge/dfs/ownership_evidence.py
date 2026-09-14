from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Mapping

OWNERSHIP_EVIDENCE_EPOCH_UTC = datetime(2026, 9, 14, 5, 0, tzinfo=timezone.utc)
_SLOT_RE = re.compile(r"(?:^|(?<=\)\s))(P|C|1B|2B|3B|SS|OF|UTIL)(?=\s)")
_ID_SUFFIX_RE = re.compile(r"\s*\((\d+)\)\s*$")


class OwnershipEvidenceError(ValueError):
    pass


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_TIMESTAMP_MUST_BE_AWARE")
    return dt.astimezone(timezone.utc)


def _norm_name(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _lineup_players(text: str) -> tuple[str, ...]:
    matches = list(_SLOT_RE.finditer(str(text or "")))
    players: list[str] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        player = text[start:end].strip()
        if player:
            players.append(player)
    return tuple(players)


def _column(fieldnames: list[str] | None, *candidates: str) -> str | None:
    if not fieldnames:
        return None
    lookup = {str(name).casefold(): str(name) for name in fieldnames if name is not None}
    for candidate in candidates:
        found = lookup.get(candidate.casefold())
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class RealizedOwnershipSnapshot:
    contest_id: str
    our_entry_id: str
    slate_lock_utc: str
    captured_at_utc: str
    source_sha256: str
    entrant_count: int
    roster_size: int
    player_counts: dict[str, int]
    realized_ownership: dict[str, float]
    evidence_class: str = "RETROSPECTIVE_REALIZED_OWNERSHIP"
    may_influence_same_slate_optimization: bool = False
    version: str = "DK_REALIZED_OWNERSHIP_V1"


def build_realized_ownership_snapshot(
    csv_bytes: bytes,
    *,
    contest_id: str | int,
    our_entry_id: str | int,
    slate_lock: datetime,
    captured_at: datetime,
    player_id_by_name: Mapping[str, str] | None = None,
    expected_field_size: int | None = None,
    roster_size: int = 10,
) -> RealizedOwnershipSnapshot:
    """Compute exact realized ownership from a complete post-contest DK standings export.

    Evidence is forward-only from the frozen epoch and retrospective by construction.
    It is valid for ownership calibration on later slates and is explicitly forbidden
    from influencing the same slate. Every entrant lineup must parse completely;
    partial exports fail closed.
    """

    lock = _utc(slate_lock)
    captured = _utc(captured_at)
    if lock < OWNERSHIP_EVIDENCE_EPOCH_UTC:
        raise OwnershipEvidenceError(
            f"DFS_OWNERSHIP_PRE_EPOCH:{lock.isoformat()}:{OWNERSHIP_EVIDENCE_EPOCH_UTC.isoformat()}"
        )
    if captured < lock:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_CAPTURE_PRELOCK")
    if roster_size < 1:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_ROSTER_SIZE_INVALID")

    try:
        text = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_CSV_ENCODING_INVALID") from exc
    reader = csv.DictReader(io.StringIO(text))
    lineup_col = _column(reader.fieldnames, "Lineup", "Roster")
    entry_col = _column(reader.fieldnames, "EntryId", "Entry ID", "EntryID")
    if lineup_col is None or entry_col is None:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_REQUIRED_COLUMNS_MISSING")

    name_map = {_norm_name(name): str(pid) for name, pid in (player_id_by_name or {}).items()}
    our_entry = str(our_entry_id)
    found_ours = False
    rows = 0
    counts: dict[str, int] = {}
    for row in reader:
        if not isinstance(row, dict):
            continue
        entry_id = str(row.get(entry_col) or "").strip()
        lineup = str(row.get(lineup_col) or "")
        if not entry_id or not lineup:
            raise OwnershipEvidenceError("DFS_OWNERSHIP_ROW_INCOMPLETE")
        if entry_id == our_entry:
            found_ours = True
        names = _lineup_players(lineup)
        if len(names) != roster_size:
            raise OwnershipEvidenceError(
                f"DFS_OWNERSHIP_LINEUP_PARSE_INCOMPLETE:{entry_id}:{len(names)}:{roster_size}"
            )
        player_ids: list[str] = []
        for raw_name in names:
            match = _ID_SUFFIX_RE.search(raw_name)
            if match:
                pid = match.group(1)
            else:
                pid = name_map.get(_norm_name(raw_name), "")
            if not pid:
                raise OwnershipEvidenceError(
                    f"DFS_OWNERSHIP_PLAYER_ID_UNRESOLVED:{entry_id}:{raw_name}"
                )
            player_ids.append(pid)
        if len(set(player_ids)) != roster_size:
            raise OwnershipEvidenceError(f"DFS_OWNERSHIP_DUPLICATE_PLAYER:{entry_id}")
        rows += 1
        for pid in player_ids:
            counts[pid] = counts.get(pid, 0) + 1

    if rows == 0:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_EXPORT_EMPTY")
    if expected_field_size is not None and rows != int(expected_field_size):
        raise OwnershipEvidenceError(
            f"DFS_OWNERSHIP_FIELD_INCOMPLETE:{rows}:{int(expected_field_size)}"
        )
    if not found_ours:
        raise OwnershipEvidenceError("DFS_OWNERSHIP_OUR_ENTRY_NOT_FOUND")

    ownership = {pid: count / rows for pid, count in sorted(counts.items())}
    return RealizedOwnershipSnapshot(
        contest_id=str(contest_id),
        our_entry_id=our_entry,
        slate_lock_utc=lock.isoformat(),
        captured_at_utc=captured.isoformat(),
        source_sha256=sha256(csv_bytes).hexdigest(),
        entrant_count=rows,
        roster_size=roster_size,
        player_counts=dict(sorted(counts.items())),
        realized_ownership=ownership,
    )


def freeze_realized_ownership(
    csv_path: str | Path,
    *,
    output_dir: str | Path,
    contest_id: str | int,
    our_entry_id: str | int,
    slate_lock: datetime,
    captured_at: datetime | None = None,
    player_id_by_name: Mapping[str, str] | None = None,
    expected_field_size: int | None = None,
    roster_size: int = 10,
) -> tuple[RealizedOwnershipSnapshot, Path]:
    path = Path(csv_path)
    raw = path.read_bytes()
    captured = captured_at or datetime.now(timezone.utc)
    snapshot = build_realized_ownership_snapshot(
        raw,
        contest_id=contest_id,
        our_entry_id=our_entry_id,
        slate_lock=slate_lock,
        captured_at=captured,
        player_id_by_name=player_id_by_name,
        expected_field_size=expected_field_size,
        roster_size=roster_size,
    )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"dk_ownership_{snapshot.contest_id}_{snapshot.source_sha256[:12]}.json"
    payload = json.dumps(asdict(snapshot), sort_keys=True, indent=2) + "\n"
    if out.exists():
        if out.read_text(encoding="utf-8") != payload:
            raise OwnershipEvidenceError("DFS_OWNERSHIP_IMMUTABLE_FREEZE_CONFLICT")
        return snapshot, out
    out.write_text(payload, encoding="utf-8")
    return snapshot, out
