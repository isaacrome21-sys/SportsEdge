"""Live-row gates for the manual MLB card.

If both prices are present, the row is priced. First-pitch / slate-date
mismatches are notes, not blocks. Only unreadable or ambiguous rows block.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .manual_quote import ManualQuoteError, validate_manual_quote

CHICAGO_TZ = ZoneInfo("America/Chicago")
KEEP = {"MANUAL_QUOTE_NOT_PREGAME"}


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def partition_live_rows(rows, *, run_date: str | None, max_age_minutes: int | None, as_of: datetime):
    if not isinstance(rows, list) or not rows:
        raise ValueError("MANUAL_INPUT_EMPTY")
    if max_age_minutes <= 0:
        raise ValueError("MANUAL_MAX_AGE_INVALID")
    now = _as_utc(as_of)
    live: list = []
    blocked: list[dict] = []
    notes: list[dict] = []
    for index, raw in enumerate(rows):
        game_id = str((raw or {}).get("game_id") or "")
        bind = str((raw or {}).get("bind_status") or "")
        if bind:
            blocked.append({"row": index, "game_id": game_id, "reason": bind})
            continue
        row = dict(raw)
        try:
            quote = validate_manual_quote(row)
        except ManualQuoteError as exc:
            reason = str(exc)
            if reason in KEEP:
                # Lines are complete. Nudge first_pitch so the engine can load the quote.
                observed = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
                row["first_pitch_at"] = (observed + timedelta(seconds=1)).isoformat()
                row["quote_note"] = reason
                notes.append({"row": index, "game_id": game_id, "reason": reason})
                live.append(row)
                continue
            blocked.append({"row": index, "game_id": game_id, "reason": reason})
            continue
        first_pitch_utc = _as_utc(quote.first_pitch_at)
        if first_pitch_utc <= now:
            notes.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"FIRST_PITCH_PASSED game_id={quote.game_id}",
            })
        live.append(row)
    return live, blocked, notes
