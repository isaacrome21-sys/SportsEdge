"""Research-only pregame source screen; no capture, admission or PLAY authority."""
from datetime import datetime, timezone
from urllib.parse import urlsplit
import re

FACT_KINDS = {"STARTER", "LINEUP", "INJURY", "AVAILABILITY", "PARTICIPATION", "ROTATION", "QB_AVAILABILITY", "GAME_STATUS"}
HASH = re.compile(r"^[0-9a-f]{64}$")
X_BASE_DOMAINS = frozenset({"x.com", "twitter.com"})


def _is_x_host(host):
    """Exact domain or DNS-label subdomain, never substring lookalikes."""
    if not isinstance(host, str):
        return False
    normalized = host.lower().rstrip(".")
    return any(normalized == base or normalized.endswith("." + base)
               for base in X_BASE_DOMAINS)


def _time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp missing")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone aware")
    return dt.astimezone(timezone.utc)


def _host(url):
    if not isinstance(url, str):
        raise ValueError("URL missing")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("HTTPS pinned host required")
    return parsed.hostname.lower()


def _screen(row, pins, event_id, subject_id, kind, cutoff, max_age):
    if not isinstance(row, dict):
        raise ValueError("row not an object")
    pin = pins.get(row.get("source_id"))
    if not isinstance(pin, dict):
        raise ValueError("source not pinned")
    if pin.get("kind") not in ("OFFICIAL", "VERIFIED_REPORTER", "SOCIAL"):
        raise ValueError("invalid pinned kind")
    hosts = pin.get("hosts")
    if not isinstance(hosts, (list, tuple)) or not hosts or any(type(h) is not str for h in hosts):
        raise ValueError("missing pinned hosts")
    source_host = _host(row.get("source_url"))
    # An X post is social evidence even if a caller mislabels its source pin.
    if _is_x_host(source_host) and pin["kind"] != "SOCIAL":
        raise ValueError("X source cannot be official or verified reporter")
    if source_host not in [h.lower() for h in hosts]:
        raise ValueError("source host mismatch")
    digest = pin.get("anchor_sha256")
    if type(digest) is not str or not HASH.fullmatch(digest) or row.get("anchor_sha256") != digest:
        raise ValueError("source anchor mismatch")
    if row.get("source_kind") != pin["kind"]:
        raise ValueError("source kind mismatch")
    if row.get("event_id") != event_id or type(row.get("subject_id")) is not int or row["subject_id"] != subject_id or row.get("fact_kind") != kind:
        raise ValueError("fact identity mismatch")
    value = row.get("value")
    if not isinstance(value, str) or not value.strip() or value.strip().upper() in ("UNKNOWN", "TBD", "NONE"):
        raise ValueError("unknown value")
    if not isinstance(row.get("raw_sha256"), str) or not HASH.fullmatch(row["raw_sha256"]):
        raise ValueError("missing raw hash")
    published = _time(row.get("published_at_utc"))
    observed = _time(row.get("observed_at_utc"))
    fetched = _time(row.get("fetched_at_utc"))
    if published > fetched or observed > fetched or fetched > cutoff:
        raise ValueError("post-cutoff or inconsistent evidence time")
    confirmation = row.get("confirmation")
    if confirmation not in ("CONFIRMED", "CORROBORATED", "RUMOR", "UNCONFIRMED"):
        raise ValueError("invalid confirmation")
    if pin["kind"] == "SOCIAL" and confirmation == "CONFIRMED":
        raise ValueError("social rumor cannot self-confirm")
    # Re-fetching an old article does not make its underlying fact fresh.
    # Require both publication and observation to be recent at the cutoff.
    fresh = all(0 <= (cutoff - stamp).total_seconds() <= max_age
                for stamp in (published, observed, fetched))
    return {"source_id": row["source_id"], "source_url": row["source_url"],
            "kind": pin["kind"], "value": value.strip(), "confirmation": confirmation,
            "published_at_utc": published.isoformat(),
            "observed_at_utc": observed.isoformat(),
            "fetched_at_utc": fetched.isoformat(),
            "pre_event_cutoff_utc": cutoff.isoformat(),
            "fresh": fresh}


def adjudicate_pregame_fact(*, event_id, subject_id, fact_kind, cutoff_utc,
                            evidence, source_registry, search_log=(), max_age_seconds=3600):
    """Only screens declared metadata; caller must verify source and receipt authenticity."""
    cutoff = _time(cutoff_utc)
    if type(event_id) is not str or not event_id or type(subject_id) is not int or subject_id <= 0 or fact_kind not in FACT_KINDS:
        raise ValueError("invalid fact identity")
    if type(max_age_seconds) is not int or max_age_seconds < 0 or not isinstance(source_registry, dict) or not isinstance(evidence, (list, tuple)):
        raise ValueError("invalid input")
    valid, rejected = [], []
    for index, row in enumerate(evidence):
        try:
            valid.append(_screen(row, source_registry, event_id, subject_id, fact_kind, cutoff, max_age_seconds))
        except (ValueError, TypeError, KeyError) as exc:
            rejected.append({"index": index, "reason": str(exc)})
    fresh = [r for r in valid if r["fresh"]]
    credible = [r for r in fresh if r["kind"] != "SOCIAL" and r["confirmation"] in ("CONFIRMED", "CORROBORATED")]
    official = [r for r in credible if r["kind"] == "OFFICIAL" and r["confirmation"] == "CONFIRMED"]
    if rejected:
        state, reason, value = "BLOCKED", "INVALID_OR_POST_CUTOFF_EVIDENCE", None
    elif len({r["value"] for r in credible}) > 1:
        state, reason, value = "BLOCKED", "CONTRADICTORY_CREDIBLE_SOURCES", None
    elif not official:
        state, reason, value = "UNKNOWN", ("SOURCE_EVIDENCE_MISSING" if not valid else "SOURCE_EVIDENCE_STALE" if not fresh else "OFFICIAL_CONFIRMATION_MISSING"), None
    else:
        state, reason, value = "SUPPORTED_RESEARCH_ONLY", "OFFICIAL_PRE_CUTOFF", official[0]["value"]
    # Search entries are caller declarations, NOT independently authenticated
    # browsing receipts. Validate the channel against pinned research hosts so
    # an X URL cannot masquerade as an official-source search (or vice versa).
    # Neither a declared search nor a pinned host establishes content truth.
    channels = set()
    credible_hosts = {
        host.lower()
        for pin in source_registry.values()
        if isinstance(pin, dict) and pin.get("kind") in ("OFFICIAL", "VERIFIED_REPORTER")
        for host in (pin.get("hosts") if isinstance(pin.get("hosts"), (list, tuple)) else ())
        if isinstance(host, str) and not _is_x_host(host)
    }
    if isinstance(search_log, (list, tuple)):
        for row in search_log:
            if not isinstance(row, dict) or row.get("channel") not in ("OFFICIAL_WEB", "X") or not isinstance(row.get("query"), str) or not row["query"].strip():
                continue
            try:
                searched_at = _time(row.get("searched_at_utc"))
                age_seconds = (cutoff - searched_at).total_seconds()
                if not 0 <= age_seconds <= max_age_seconds:
                    continue
                host = _host(row.get("search_url"))
                if row["channel"] == "X" and _is_x_host(host):
                    channels.add("X")
                elif row["channel"] == "OFFICIAL_WEB" and host in credible_hosts:
                    channels.add("OFFICIAL_WEB")
            except ValueError:
                continue
    return {"schema": "SPORTSEDGE_PREGAME_FACT_PROVENANCE_V1",
            "state": state, "reason": reason, "value": value,
            "accepted_sources": valid, "rejected_sources": rejected,
            "search_channels_pre_cutoff": sorted(channels),
            "missing_search_channels": [c for c in ("OFFICIAL_WEB", "X") if c not in channels],
            "search_execution_verified": False,
            "source_authenticity_verified": False, "receipt_bytes_verified": False,
            "model_probability_verified": False, "play_authority": False,
            "pricing_authority": False, "staking_authority": False}
