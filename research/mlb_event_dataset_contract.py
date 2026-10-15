"""Research-only validation of timestamped MLB batter event records.

This checks structural and chronological integrity, not source authenticity.
"""
from datetime import datetime, timezone
from math import isfinite

def _utc(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return parsed.astimezone(timezone.utc)

def validate_events(rows, *, training_cutoff):
    """Require strictly ordered event timestamps and pre-event observation."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("EMPTY_DATASET")
    cutoff = _utc(training_cutoff)
    previous = cutoff
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("INVALID_RECORD")
        event = _utc(row.get("event_time"))
        observed = _utc(row.get("observed_at"))
        if event <= previous:
            raise ValueError("NON_CHRONOLOGICAL_OR_TRAIN_OVERLAP")
        if observed > event or observed > cutoff:
            raise ValueError("UNVERIFIED_PRE_EVENT_AVAILABILITY")
        previous = event
        event_id = row.get("event_id")
        player_id = row.get("player_id")
        outcome = row.get("outcome")
        source = row.get("source_url")
        if not isinstance(event_id, str) or not event_id or event_id in seen:
            raise ValueError("DUPLICATE_OR_INVALID_EVENT_ID")
        if not isinstance(player_id, (str, int)) or isinstance(player_id, bool) or not str(player_id):
            raise ValueError("INVALID_PLAYER")
        if type(outcome) is not int or outcome not in (0, 1):
            raise ValueError("INVALID_OUTCOME")
        if not isinstance(source, str) or not source.startswith("https://"):
            raise ValueError("INVALID_SOURCE")
        seen.add(event_id)
    return {"n":len(rows), "schema_valid":True, "source_authenticity_verified":False,
            "market_probability_verified":False, "play_authorized":False, "research_only":True}
