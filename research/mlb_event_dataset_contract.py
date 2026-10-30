"""Research-only chronological MLB event schema; no source authenticity claims."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

def _utc(value):
    if not isinstance(value,str):
        raise ValueError("INVALID_TIMESTAMP")
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIMESTAMP") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("NAIVE_TIMESTAMP")
    return parsed.astimezone(timezone.utc)

def validate_events(rows, *, training_cutoff):
    """Validate pre-event prediction timestamps and post-event outcome timestamps.

    Rows must be ordered strictly by event time. Prediction availability must
    precede its event; outcome availability must not precede its event.
    Source URL structure is checked but its authenticity is NOT established.
    """
    if not isinstance(rows,list) or not rows:
        raise ValueError("EMPTY_DATASET")
    previous=_utc(training_cutoff)
    seen=set()
    for row in rows:
        if not isinstance(row,dict):
            raise ValueError("INVALID_RECORD")
        event=_utc(row.get("event_time"))
        prediction=_utc(row.get("prediction_observed_at"))
        outcome_observed=_utc(row.get("outcome_observed_at"))
        if event<=previous:
            raise ValueError("NON_CHRONOLOGICAL_OR_TRAIN_OVERLAP")
        if prediction>=event:
            raise ValueError("PREDICTION_NOT_PRE_EVENT")
        if outcome_observed<event:
            raise ValueError("OUTCOME_BEFORE_EVENT")
        previous=event
        event_id=row.get("event_id")
        player_id=row.get("player_id")
        outcome=row.get("outcome")
        source=row.get("source_url")
        if not isinstance(event_id,str) or not event_id or event_id in seen:
            raise ValueError("DUPLICATE_OR_INVALID_EVENT_ID")
        if not isinstance(player_id,(str,int)) or isinstance(player_id,bool) or not str(player_id):
            raise ValueError("INVALID_PLAYER")
        if type(outcome) is not int or outcome not in (0,1):
            raise ValueError("INVALID_OUTCOME")
        if not isinstance(source,str):
            raise ValueError("INVALID_SOURCE")
        parsed=urlsplit(source)
        if parsed.scheme!="https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("INVALID_SOURCE")
        seen.add(event_id)
    return {"n":len(rows),"schema_valid":True,"source_authenticity_verified":False,
            "prediction_provenance_verified":False,"market_probability_verified":False,
            "play_authorized":False,"research_only":True}
