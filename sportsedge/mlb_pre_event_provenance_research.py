"""Offline provenance audit for uncertain MLB pre-event facts.

This module NEVER authenticates sources or promotes an availability/lineup fact.
It records caller-supplied URL/time evidence for later independent verification.
No network calls, betting odds, or live capture are performed here.
"""
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


def _utc(value):
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp required")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone aware")
    return parsed.astimezone(timezone.utc)


def _hostname(url):
    if not isinstance(url, str):
        raise ValueError("source_url required")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or any(c.isspace() for c in url)):
        raise ValueError("source_url must be an HTTPS URL without credentials")
    host = parsed.hostname.rstrip(".").lower()
    if not host or host.startswith(".") or ".." in host:
        raise ValueError("invalid source hostname")
    return host


def _is_x(host):
    return any(host == domain or host.endswith("." + domain)
               for domain in ("x.com", "twitter.com"))


def audit_pre_event_fact(fact_key, cutoff_utc, observations, *, freshness_hours=24):
    """Audit submitted observations, fail closed, and require WEB plus X coverage.

    An official-looking URL or a caller-supplied source class is not proof of
    source authenticity. Thus even an apparently uncontested official claim is
    a CANDIDATE, never a confirmed active/starting player or a priced market.
    """
    if not isinstance(fact_key, str) or not fact_key.strip():
        raise ValueError("fact_key required")
    cutoff = _utc(cutoff_utc)
    if type(freshness_hours) not in (int, float) or not 0 < freshness_hours <= 168:
        raise ValueError("invalid freshness_hours")
    if not isinstance(observations, (list, tuple)):
        raise ValueError("observations must be a sequence")
    records = []
    channels = set()
    primary_claims = set()
    secondary_claims = set()
    for obs in observations:
        if not isinstance(obs, dict):
            raise ValueError("observation must be an object")
        url = obs.get("source_url")
        host = _hostname(url)
        published = _utc(obs.get("published_at_utc"))
        observed = _utc(obs.get("observed_at_utc"))
        channel = obs.get("channel")
        source_class = obs.get("source_class")
        claim = obs.get("claim")
        if channel not in ("WEB", "X") or source_class not in (
                "OFFICIAL", "VERIFIED_REPORTER", "RUMOR", "OTHER"):
            raise ValueError("invalid channel/source_class")
        if not isinstance(claim, str) or not claim.strip():
            raise ValueError("claim required")
        # Prevent caller-controlled labels from laundering X into official web.
        if (channel == "X") != _is_x(host):
            raise ValueError("channel does not match source host")
        if published > observed or observed > cutoff:
            reason = "POST_CUTOFF_OR_CLOCK_CONFLICT"
        elif cutoff - observed > timedelta(hours=freshness_hours):
            reason = "STALE"
        else:
            reason = "TIMELY_UNAUTHENTICATED"
            channels.add(channel)
            if channel == "WEB" and source_class == "OFFICIAL":
                primary_claims.add(claim.strip().upper())
            elif source_class in ("OFFICIAL", "VERIFIED_REPORTER"):
                secondary_claims.add(claim.strip().upper())
        records.append({
            "source_url": url, "published_at_utc": published.isoformat(),
            "observed_at_utc": observed.isoformat(),
            "pre_event_cutoff_utc": cutoff.isoformat(), "channel": channel,
            "source_class": source_class, "claim": claim,
            "evidence_state": reason,
        })
    all_claims = primary_claims | secondary_claims
    if len(all_claims) > 1:
        blocker = "CONTRADICTORY_CLAIMS"
    elif channels != {"WEB", "X"}:
        blocker = "WEB_AND_X_COVERAGE_REQUIRED"
    elif not primary_claims:
        blocker = "OFFICIAL_PRIMARY_MISSING"
    else:
        blocker = "SOURCE_AUTHENTICITY_NOT_INDEPENDENTLY_VERIFIED"
    return {
        "schema": "SPORTSEDGE_MLB_PRE_EVENT_PROVENANCE_RESEARCH_V1",
        "fact_key": fact_key, "pre_event_cutoff_utc": cutoff.isoformat(),
        "observations": records, "timely_channels": sorted(channels),
        "candidate_claim": next(iter(primary_claims)) if len(primary_claims) == 1 else None,
        "resolved_status": "UNKNOWN", "blocker": blocker,
        "source_authenticity_verified": False,
        "market_probability_verified": False, "pricing_authority": False,
        "play_authority": False, "staking_authority": False,
    }
