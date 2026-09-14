from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import io
import json
from pathlib import Path
import re
from typing import Iterable

from .rules import get_rules
from .sources.common import normalize_name

_SLOT_ALIASES = {
    "S-FLEX": "SUPERFLEX",
    "SUPER FLEX": "SUPERFLEX",
    "SUPER-FLEX": "SUPERFLEX",
    "D/ST": "DST",
    "DEF": "DST",
}


@dataclass(frozen=True)
class OwnershipPlayerEvidence:
    display_name: str
    normalized_name: str
    lineup_count: int
    ownership: float


@dataclass(frozen=True)
class OwnershipSlateEvidence:
    schema_version: int
    sport: str
    contest_id: str
    contest_name: str
    draft_group_id: str
    slate_start: str
    captured_at: str
    valid_entries: int
    player_count: int
    source_sha256: str
    players: tuple[OwnershipPlayerEvidence, ...]

    def to_dict(self) -> dict:
        return {
            **{k: v for k, v in asdict(self).items() if k != "players"},
            "players": [asdict(p) for p in self.players],
        }


def _normalize_slot(value: str) -> str:
    raw = re.sub(r"\s+", " ", str(value or "").strip().upper())
    return _SLOT_ALIASES.get(raw, raw)


def _slot_pattern(slots: Iterable[str]) -> re.Pattern[str]:
    labels = {_normalize_slot(slot) for slot in slots}
    labels.update({"S-FLEX" if x == "SUPERFLEX" else x for x in labels})
    labels.update({"D/ST" if x == "DST" else x for x in labels})
    ordered = sorted(labels, key=len, reverse=True)
    body = "|".join(re.escape(x) for x in ordered)
    return re.compile(rf"(?<!\S)({body})(?=\s)", flags=re.IGNORECASE)


def parse_lineup(lineup: str, sport: str) -> tuple[str, ...]:
    """Parse one DraftKings standings-export lineup into player display names.

    We require the exact sport roster-slot sequence. A malformed row blocks the
    evidence ingest rather than being partially counted, because partial ownership
    is worse than no ownership evidence.
    """
    rules = get_rules(sport)
    text = re.sub(r"\s+", " ", str(lineup or "").strip())
    if not text:
        raise ValueError("DFS_OWNERSHIP_LINEUP_EMPTY")
    pattern = _slot_pattern(rules.slots)
    matches = list(pattern.finditer(text))
    parsed_slots = tuple(_normalize_slot(m.group(1)) for m in matches)
    expected = tuple(_normalize_slot(x) for x in rules.slots)
    if parsed_slots != expected:
        raise ValueError(
            "DFS_OWNERSHIP_SLOT_SEQUENCE_INVALID:"
            f"expected={','.join(expected)}:got={','.join(parsed_slots)}"
        )
    names: list[str] = []
    for idx, match in enumerate(matches):
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        name = text[start:end].strip(" ,")
        if not name:
            raise ValueError(f"DFS_OWNERSHIP_PLAYER_NAME_EMPTY:{expected[idx]}")
        names.append(name)
    if len(names) != len(expected):
        raise ValueError("DFS_OWNERSHIP_ROSTER_SIZE_INVALID")
    return tuple(names)


def ingest_standings_csv(
    raw: bytes,
    *,
    sport: str,
    contest_id: str,
    contest_name: str = "",
    draft_group_id: str = "",
    slate_start: datetime | None = None,
    captured_at: datetime | None = None,
) -> OwnershipSlateEvidence:
    if not contest_id.strip():
        raise ValueError("DFS_OWNERSHIP_CONTEST_ID_REQUIRED")
    if slate_start is not None and (slate_start.tzinfo is None or slate_start.utcoffset() is None):
        raise ValueError("DFS_OWNERSHIP_SLATE_START_TIMEZONE_REQUIRED")
    captured = captured_at or datetime.now(timezone.utc)
    if captured.tzinfo is None or captured.utcoffset() is None:
        raise ValueError("DFS_OWNERSHIP_CAPTURE_TIMEZONE_REQUIRED")
    source_sha = sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("DFS_OWNERSHIP_CSV_ENCODING_INVALID") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("DFS_OWNERSHIP_CSV_HEADER_MISSING")
    lineup_key = next((x for x in reader.fieldnames if str(x).strip().casefold() == "lineup"), None)
    if lineup_key is None:
        raise ValueError("DFS_OWNERSHIP_LINEUP_COLUMN_MISSING")

    counts: dict[str, int] = {}
    display: dict[str, str] = {}
    valid_entries = 0
    for row_number, row in enumerate(reader, start=2):
        lineup_text = str(row.get(lineup_key) or "").strip()
        if not lineup_text:
            continue
        try:
            names = parse_lineup(lineup_text, sport)
        except ValueError as exc:
            raise ValueError(f"DFS_OWNERSHIP_MALFORMED_ROW:{row_number}:{exc}") from exc
        normalized = [normalize_name(name) for name in names]
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"DFS_OWNERSHIP_DUPLICATE_PLAYER_ROW:{row_number}")
        valid_entries += 1
        for name, key in zip(names, normalized):
            if not key:
                raise ValueError(f"DFS_OWNERSHIP_NORMALIZED_NAME_EMPTY:{row_number}")
            counts[key] = counts.get(key, 0) + 1
            display.setdefault(key, name)
    if valid_entries < 1:
        raise ValueError("DFS_OWNERSHIP_NO_VALID_ENTRIES")

    players = tuple(
        OwnershipPlayerEvidence(
            display_name=display[key],
            normalized_name=key,
            lineup_count=count,
            ownership=count / valid_entries,
        )
        for key, count in sorted(counts.items(), key=lambda kv: (-kv[1], display[kv[0]].casefold()))
    )
    return OwnershipSlateEvidence(
        schema_version=1,
        sport=sport.upper(),
        contest_id=contest_id.strip(),
        contest_name=contest_name.strip(),
        draft_group_id=str(draft_group_id or "").strip(),
        slate_start=slate_start.astimezone(timezone.utc).isoformat() if slate_start else "",
        captured_at=captured.astimezone(timezone.utc).isoformat(),
        valid_entries=valid_entries,
        player_count=len(players),
        source_sha256=source_sha,
        players=players,
    )


def write_immutable_evidence(evidence: OwnershipSlateEvidence, output: str | Path) -> Path:
    path = Path(output)
    if path.exists():
        raise FileExistsError(f"DFS_OWNERSHIP_EVIDENCE_ALREADY_EXISTS:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(evidence.to_dict(), sort_keys=True, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    return path
