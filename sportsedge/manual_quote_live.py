"""Live-row gates for the manual MLB card. Fail per row, not the whole slate."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .manual_quote import ManualQuoteError, validate_manual_quote

CHICAGO_TZ = ZoneInfo("America/Chicago")


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
    allowed = set()
    if run_date:
        start = datetime.fromisoformat(run_date).date()
        allowed = {start.isoformat(), (start + timedelta(days=1)).isoformat()}
    live: list = []
    blocked: list[dict] = []
    for index, raw in enumerate(rows):
        game_id = str((raw or {}).get("game_id") or "")
        bind = str((raw or {}).get("bind_status") or "")
        if bind:
            blocked.append({"row": index, "game_id": game_id, "reason": bind})
            continue
        try:
            quote = validate_manual_quote(raw)
        except ManualQuoteError as exc:
            blocked.append({"row": index, "game_id": game_id, "reason": str(exc)})
            continue
        first_pitch_utc = _as_utc(quote.first_pitch_at)
        first_pitch_ct_date = first_pitch_utc.astimezone(CHICAGO_TZ).date().isoformat()
        if allowed and first_pitch_ct_date not in allowed:
            blocked.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": (
                    f"MANUAL_INPUT_DATE_MISMATCH expected={run_date} "
                    f"first_pitch_date_ct={first_pitch_ct_date}"
                ),
            })
            continue
        if first_pitch_utc <= now:
            blocked.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_QUOTE_GAME_STARTED game_id={quote.game_id}",
            })
            continue
        observed_utc = _as_utc(quote.observed_at)
        if (now - observed_utc).total_seconds() / 60.0 < 0:
            blocked.append({
                "row": index,
                "game_id": quote.game_id,
                "reason": f"MANUAL_QUOTE_FROM_FUTURE game_id={quote.game_id}",
            })
            continue
        live.append(raw)
    return live, blocked
