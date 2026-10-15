"""Research-only evidence attestation: a boolean alone never verifies a market."""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from sportsedge.dk_market_coverage_contract import REQUIRED_EVIDENCE


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_https_url(value):
    if not isinstance(value, str) or value != value.strip():
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == "https" and bool(host) and
            parts.username is None and parts.password is None and
            port in (None, 443) and not any(ch.isspace() or ord(ch) < 32 for ch in value) and
            "\\\\" not in value and parts.fragment == "")


def review_attestations(evidence: dict, *, cutoff: str) -> dict:
    """Fail closed on missing, unanchored, future or post-cutoff evidence.

    An attestation must identify a source URL and an observed timestamp.
    Source observation is not proof of publication or a verified sports fact.
    """
    boundary = _timestamp(cutoff)
    if boundary is None:
        raise ValueError("INVALID_CUTOFF")
    missing = []
    for field in REQUIRED_EVIDENCE:
        record = evidence.get(field)
        if not isinstance(record, dict) or record.get("verified") is not True:
            missing.append(field)
            continue
        url = record.get("source_url")
        observed = _timestamp(record.get("observed_at"))
        published = _timestamp(record.get("published_at"))
        if not _safe_https_url(url):
            missing.append(field)
        elif observed is None or published is None or published > observed or observed > boundary:
            missing.append(field)
    return {
        "status": "UNVERIFIED" if missing else "EVIDENCE_COMPLETE_REVIEW_REQUIRED",
        "missing_evidence": missing,
        "play_authorized": False,
    }
