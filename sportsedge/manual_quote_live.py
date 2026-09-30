"""Live-row gates for the manual MLB card.

Complete two-sided lines still price on the phone card. Time/date mismatches
are recorded as violations so validate_live_rows can raise the old strings.
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


def inspect_live_rows(rows, *, run_date: str | None, max_age_minutes: int | None, as_of: datetime):
    if not isinstance(rows, list) or not rows:
        raise ValueError("MANUAL_INPUT_EMPTY")
    if max_age_minutes <= 0:
        raise ValueError("MANUAL_MAX_AGE_INVALID")
    now = _as_utc(as_of)
    live: list = []
    blocked: list[dict] = []
    notes: list[dict] = []
    violations: list[dict] = []
    for index, raw in enumerate(rows):
        game_id = str((raw or {}).get("game_id") or "")
        bind = str((raw or {}).get("bind_status") or "")
        if bind:
            item = {"row": index, "game_id": game_id, "reason": bind}
            blocked.append(item)
            continue
        row = dict(raw)
        try:
            quote = validate_manual_quote(row)
        except ManualQuoteError as exc:
            reason = str(exc)
            if reason in KEEP:
                observed = datetime.fromisoformat(str(row["observed_at"]).replace("Z", "+00:00"))
                row["first_pitch_at"] = (observed + timedelta(seconds=1)).isoformat()
                row["quote_note"] = reason
                notes.append({"row": index, "game_id": game_id, "reason": reason})
                live.append(row)
                continue
            blocked.append({"row": index, "game_id": game_id, "reason": reason})
            continue
        first_pitch_utc = _as_utc(quote.first_pitch_at)
        first_pitch_ct_date = first_pitch_utc.astimezone(CHICAGO_TZ).date().isoformat()
        if run_date and first_pitch_ct_date != run_date:
            violations.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": (
                    f"MANUAL_INPUT_DATE_MISMATCH row={index} expected={run_date} "
                    f"first_pitch_date_ct={first_pitch_ct_date}"
                ),
            })
        if first_pitch_utc <= now:
            violations.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_QUOTE_GAME_STARTED row={index} game_id={quote.game_id}",
            })
            notes.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"FIRST_PITCH_PASSED game_id={quote.game_id}",
            })
        observed_utc = _as_utc(quote.observed_at)
        if (now - observed_utc).total_seconds() / 60.0 < 0:
            violations.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_QUOTE_FROM_FUTURE row={index} game_id={quote.game_id}",
            })
        live.append(row)
    return live, blocked, notes, violations


def partition_live_rows(rows, *, run_date: str | None, max_age_minutes: int | None, as_of: datetime):
    live, blocked, notes, _violations = inspect_live_rows(
        rows, run_date=run_date, max_age_minutes=max_age_minutes, as_of=as_of,
    )
    return live, blocked, notes


def validate_live_rows(rows, *, run_date: str | None, max_age_minutes: int | None, as_of: datetime) -> None:
    _live, blocked, _notes, violations = inspect_live_rows(
        rows, run_date=run_date, max_age_minutes=max_age_minutes, as_of=as_of,
    )
    first = (blocked + violations)[:1]
    if first:
        raise ValueError(first[0]["reason"])
