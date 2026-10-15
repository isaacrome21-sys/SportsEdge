"""Research-only point-in-time evidence reconciliation; no network or pricing.

A claimed source type is never proof of authentication. Callers must independently
search official/team and X sources and bind their observations to real evidence.
"""
from datetime import datetime, timezone
from urllib.parse import urlsplit

ALLOWED_FACTS = frozenset({
    "STARTER", "LINEUP", "INJURY", "QB_AVAILABILITY", "PARTICIPATION",
    "ROTATION", "GAME_STATUS", "GOALIE", "PITCHER_AVAILABILITY",
})
CREDIBLE_KINDS = frozenset({"OFFICIAL_LEAGUE", "OFFICIAL_TEAM", "VERIFIED_REPORTER"})


def _time(value):
    if not isinstance(value, str):
        raise ValueError("INVALID_TIME")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("INVALID_TIME") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("NAIVE_TIME")
    return dt.astimezone(timezone.utc)


def _source(url):
    if not isinstance(url, str):
        return False
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    return (parsed.scheme == "https" and bool(parsed.hostname)
            and not parsed.username and not parsed.password)


def reconcile(records, *, game_id, subject_id, fact_type, as_of,
              event_time, pre_event_cutoff, max_age_seconds=21600):
    """Conservatively reconcile timestamped *claims* available before an event.

    Invalid, contradictory, stale, missing, and X-only evidence blocks.
    No result authenticates sources or authorizes market pricing.
    """
    if (not isinstance(records, list) or
            not all(isinstance(x, str) and bool(x)
                    for x in (game_id, subject_id, fact_type)) or
            fact_type not in ALLOWED_FACTS):
        raise ValueError("INVALID_REQUEST")
    if type(max_age_seconds) is not int or not 0 < max_age_seconds <= 21600:
        raise ValueError("INVALID_MAX_AGE")
    now, event, cutoff = _time(as_of), _time(event_time), _time(pre_event_cutoff)
    if not (now <= cutoff <= event):
        raise ValueError("INVALID_CUTOFF")
    reasons = []
    values = set()
    credible = 0
    x_claims = 0
    for index, row in enumerate(records):
        if not isinstance(row, dict):
            reasons.append((index, "INVALID_RECORD"))
            continue
        if ((row.get("game_id"), row.get("subject_id"), row.get("fact_type"))
                != (game_id, subject_id, fact_type)):
            reasons.append((index, "IDENTITY_MISMATCH"))
            continue
        kind, value = row.get("source_kind"), row.get("fact_value")
        if not _source(row.get("source_url")) or not isinstance(value, str) or not value:
            reasons.append((index, "INVALID_SOURCE_OR_VALUE"))
            continue
        try:
            published = _time(row.get("published_at"))
            observed = _time(row.get("observed_at"))
        except ValueError:
            reasons.append((index, "INVALID_TIMESTAMP"))
            continue
        if not (published <= observed <= now <= cutoff <= event):
            reasons.append((index, "LATE_OR_FUTURE_EVIDENCE"))
            continue
        if (now - observed).total_seconds() > max_age_seconds:
            reasons.append((index, "STALE_EVIDENCE"))
            continue
        if kind == "X_UNVERIFIED":
            x_claims += 1
            reasons.append((index, "X_UNVERIFIED"))
            continue
        if kind not in CREDIBLE_KINDS:
            reasons.append((index, "UNVERIFIED_SOURCE_KIND"))
            continue
        credible += 1
        values.add(value)
    if len(values) > 1:
        status = "BLOCKED_CONFLICT"
    elif not credible:
        status = "BLOCKED_NO_CREDIBLE_EVIDENCE"
    elif reasons:
        status = "BLOCKED_UNRESOLVED_EVIDENCE"
    else:
        status = "PROVISIONAL_UNAUTHENTICATED"
    return {
        "status": status,
        "claimed_value": next(iter(values)) if len(values) == 1 else None,
        "credible_claims": credible,
        "x_unverified_claims": x_claims,
        "refusals": reasons,
        "source_authenticity_verified": False,
        "market_probability_verified": False,
        "pricing_eligible": False,
        "play_authorized": False,
        "research_only": True,
    }
